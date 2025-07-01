import time
import json
from dataclasses import asdict
from datetime import timedelta

from celery import chain, group
from psycopg import OperationalError
from sqlalchemy import or_

from .celery_app import celery
from app.models import *
from flask import current_app
from lolesports_api.rest_adapter import RestAdapter as LoLRestAdapter
from mlb_api.rest_adapter import RestAdapter as MLBRestAdapter
from app.seeding_helpers import get_or_create_canonical_team, get_or_create_canonical_player
from app import cache, redis_client

lolapi = LoLRestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')
mlbapi = MLBRestAdapter(hostname='statsapi.mlb.com')

# Will refactor to use this get_api later
def get_api(sport):
    if sport == 'Baseball':
        return mlbapi
    else:
        return lolapi

def update_lol_league(league:League):
    event_schedule = lolapi.get_schedule(league_name=league.name, league_id=league.league_id)
    existing_event_match_ids = {event.match_id for event in
                                Event.query.filter_by(league_id=league.id).with_entities(Event.match_id).all()}
    events_to_add = []
    for event in event_schedule.events:
        if event.match_id not in existing_event_match_ids:
            current_app.logger.info(f"SCHEDULER: Found a new event {event.match_id} for league {league.name}")
            new_event = Event(
                start_time=event.start_time,
                strategy=event.strategy,
                state=event.state,
                match_id=event.match_id,
                team_one=event.teams[0].get('name'),
                team_two=event.teams[1].get('name'),
                league_id=league.id,
                start_time_datetime=datetime.strptime(event.start_time, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc),
                is_start_scheduled=False
            )
            events_to_add.append(new_event)
    if events_to_add:
        db.session.add_all(events_to_add)
        db.session.commit()
    time.sleep(.2)

def update_mlb_league(league:League):
    today = datetime.today() - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    event_schedule = mlbapi.get_schedule(today.strftime("%Y-%m-%d"), tomorrow.strftime("%Y-%m-%d"))
    existing_event_match_ids = [int(event.match_id) for event in
                                Event.query.filter_by(league_id=league.id).with_entities(Event.match_id).all()]
    events_to_add = []
    for event in event_schedule.events:
        if event.id not in existing_event_match_ids:
            current_app.logger.info(f"SCHEDULER: Found a new event {event.id} for league {league.name}")
            state = ''
            if event.state == 'P':
                state = 'unstarted'
            elif event.state == 'L':
                state = 'inProgress'
            else:
                state = 'completed'
            new_event = Event(
                start_time=event.start_time,
                state=state,
                match_id=event.id,
                team_one=event.home_name,
                team_two=event.away_name,
                league_id=league.id,
                start_time_datetime=datetime.strptime(event.start_time, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc),
                is_start_scheduled=False
            )
            events_to_add.append(new_event)
    if events_to_add:
        db.session.add_all(events_to_add)
        db.session.commit()
    time.sleep(.2)

@celery.task(bind=True)
def update_leagues(self):
    current_app.logger.info("SCHEDULER: Running job to update leagues. Time: " + str(datetime.now(timezone.utc)))
    all_leagues = League.query.all()
    for league in all_leagues:
        if league.name != 'MLB':
            update_lol_league(league)
        else:
            update_mlb_league(league)
    current_app.logger.info("SCHEDULER: Finished task update_leagues. Time: " + str(datetime.now(timezone.utc)))

def populate_unstarted_lol_event(event:Event):
    try:
        match_details = lolapi.get_match(event.match_id)
        # Create a new match, populate with MatchTeams and players
        new_match = Match(
            event_id=event.id,
            team_one_id=match_details.team_ids[0],
            team_two_id=match_details.team_ids[1]
        )
        event.match = new_match
        db.session.add(new_match)

        api_teams_in_match = lolapi.get_teams([event.match.team_one_id, event.match.team_two_id])
        for api_team_data in api_teams_in_match:
            if api_team_data['name'] == 'TBD':
                # Make a temporary match_team
                match_team = MatchTeam(
                    name='TBD',
                    image=None,
                )
                match_team.match = new_match
                db.session.add(match_team)
                continue
            # Get Canonical Team
            canonical_team = get_or_create_canonical_team(api_team_data, event.league)
            db.session.flush()

            # Create MatchTeam
            match_team = MatchTeam(
                name=canonical_team.name,
                image=canonical_team.image,
            )
            match_team.match = new_match
            match_team.canonical_team = canonical_team
            db.session.add(match_team)

            # Create MatchPlayers
            for api_player_data in api_team_data.get('players', []):
                canonical_player = get_or_create_canonical_player(api_player_data, event.league, canonical_team)
                if canonical_player is None:
                    continue
                match_player = MatchPlayer(
                    name=canonical_player.name,
                    role=api_player_data['role'],
                    image=canonical_player.image,
                )
                match_player.match_team = match_team
                match_player.canonical_player = canonical_player
                db.session.add(match_player)
    except OperationalError as exc:
        raise self.retry(exc=exc, countdown=60, max_retries=3)
    except Exception as exc:
        current_app.logger.error("NONOperationalError Exception")
        raise

def populate_unstarted_mlb_event(event:Event):
    seed_mlb_matches(event)

@celery.task(bind=True)
# Populates newly added completed events
def populate_unstarted_events(self):
    try:
        events_to_pop = Event.query.filter(
            Event.state == 'unstarted',
            Event.match == None
        ).all()
        for event in events_to_pop:
            if event.league.name == 'MLB':
                populate_unstarted_mlb_event(event)
            else:
                populate_unstarted_lol_event(event)
            db.session.commit()
            current_app.logger.info(f"SCHEDULER: Updated Unstarted Event {event.id} in league {event.league.name}")
        current_app.logger.info("SCHEDULER: Finished populating unstarted events")
    except OperationalError as exc:
        raise self.retry(exc=exc, countdown=60, max_retries=3)
    except Exception as exc:
        current_app.logger.error("NONOperationalError Exception")
        raise

@celery.task(bind=True)
def populate_completed_events(self):
    try:
        events_to_check = Event.query.filter(
            Event.state == 'completed',
            or_(
                Event.match == None,
                Event.match.has(~Match.games.any())
            )
        ).all()
        for event in events_to_check:
            current_app.logger.info(
                f"Processing Event (PK: {event.id}, API MatchID: {event.match_id}) for match creation.")
            if event.league.name != 'MLB':
                seed_lol_matches(event)
            else:
                seed_mlb_matches(event)
        current_app.logger.info("Finished processing all new completed events")
    except OperationalError as exc:
        raise self.retry(exc=exc, countdown=60, max_retries=3)
    except Exception as exc:
        current_app.logger.error("NONOperationalError Exception")
        raise

@celery.task(bind=True)
def kick_off_league_update_workflow(self):
    """
    This is the master task that Celery Beat will schedule.
    It defines the entire workflow and starts it.
    """
    try:
        current_app.logger.info("Kicking off the main league update workflow.")

        # Define the workflow:
        # 1. Run update_leagues() first.
        # 2. Then, run the other two tasks in parallel.
        # Note: The result of update_leagues will be passed to BOTH parallel tasks.
        workflow = chain(
            update_leagues.s(),
            group(
                populate_completed_events.si(),
                populate_unstarted_events.si()
            )
        )

        # Execute the entire workflow in the background
        workflow.apply_async()

        current_app.logger.info("League update workflow has been successfully queued.")
    except OperationalError as exc:
        raise self.retry(exc=exc, countdown=60, max_retries=3)
    except Exception as exc:
        current_app.logger.error("NONOperationalError Exception")
        raise

@celery.task(name='tasks.seed_sports')
def seed_sports_task():
    current_app.logger.info("Seeding Sports")
    sports_to_add = []
    sports_to_add.append(Sport(
        name='League of Legends'
    ))
    sports_to_add.append(Sport(
        name='Baseball'
    ))
    db.session.bulk_save_objects(sports_to_add)
    db.session.commit()

@celery.task(name='tasks.seed_leagues')
def seed_leagues_task():
    current_app.logger.info("Starting task: seed_leagues_task")
    db.session.flush()
    lol_sport = Sport.query.filter_by(name='League of Legends').first()
    mlb_sport = Sport.query.filter_by(name='Baseball').first()
    ignore = ['LCL', "TFT Esports ", 'LCS', "King's Duel", 'Worlds Qualifying Series', 'LCO', 'LLA', 'CBLOL',
              'Arabian League']
    # temp change to only include MSI for testing
    #include = ['MSI']
    leagues_list = lolapi.get_leagues()
    lol_to_add = [
        League(name=league['name'], sport_id=lol_sport.id, league_id=league['id'], image=league['image'], sport=lol_sport)
        for league in leagues_list if league['name'] not in ignore
    ]
    # Not worrying about separate MLB Leagues for now.
    mlb_to_add = League(name='MLB', sport_id=mlb_sport.id, league_id='1', image='https://www.mlbstatic.com/team-logos/league-on-dark/1.svg', sport=mlb_sport)
    db.session.bulk_save_objects(lol_to_add)
    db.session.add(mlb_to_add)
    db.session.commit()
    current_app.logger.info(f"Finished seeding {len(lol_to_add)} League of Legends leagues.")
    current_app.logger.info(f"Finished seeding 1 MLB League")

# --- Stage 2 Helper ---
def seed_lol_events(league:League):
    current_app.logger.info(f"Starting to seed events for league: {league.name}")
    event_schedule = lolapi.get_schedule(league.name, league.league_id)
    existing_event_match_ids = {e.match_id for e in
                                Event.query.filter_by(league_id=league.id).with_entities(Event.match_id)}

    to_add = []
    for event_data in event_schedule.events:
        if event_data.match_id in existing_event_match_ids:
            continue

        new_event = Event(
            start_time=event_data.start_time,
            state=event_data.state,
            match_id=event_data.match_id,
            team_one=event_data.teams[0].get('name'),
            team_two=event_data.teams[1].get('name'),
            league_id=league.id,
            start_time_datetime=datetime.strptime(event_data.start_time, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc),
            is_start_scheduled=False
        )
        to_add.append(new_event)

    if to_add:
        db.session.bulk_save_objects(to_add)
        db.session.commit()
    time.sleep(0.4)  # Keep API rate limiting if necessary

def seed_mlb_events(league:League):
    # temp change to seed a day in the past
    today = datetime.today() - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    event_schedule = mlbapi.get_schedule(today.strftime("%Y-%m-%d"), tomorrow.strftime("%Y-%m-%d"))
    existing_event_match_ids = {e.match_id for e in
                                Event.query.filter_by(league_id=league.id).with_entities(Event.match_id)}
    to_add = []
    for event in event_schedule.events:
        state = ''
        if event.id in existing_event_match_ids:
            continue
        if event.state == 'P':
            state = 'unstarted'
        elif event.state == 'L':
            state = 'inProgress'
        else:
            state = 'completed'

        new_event = Event(
            start_time=event.start_time,
            state=state,
            match_id=event.id,
            team_one=event.home_name,
            team_two=event.away_name,
            league_id=league.id,
            start_time_datetime=datetime.strptime(event.start_time, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc),
            is_start_scheduled=False
        )
        to_add.append(new_event)

    if to_add:
        db.session.bulk_save_objects(to_add)
        db.session.commit()
        current_app.logger.info("END MLB SEED, added " + str(len(to_add)) + " events.")
    time.sleep(0.4)

# --- Stage 2 Task ---
@celery.task(name='tasks.seed_events_for_league')
def seed_events_for_league_task(league_id):
    """Seeds all events for a single league."""
    league = League.query.get(league_id)
    if not league:
        return
    if league.name != 'MLB':
        seed_lol_events(league)
    else:
        seed_mlb_events(league)

# --- Stage 3 Helper ---
def seed_lol_matches(event:Event):
    try:
        match_details_api = lolapi.get_match(event.match_id)

        new_match = Match(team_one_id=match_details_api.team_ids[0], team_two_id=match_details_api.team_ids[1])
        event.match = new_match

        current_match_players_map = {}
        api_teams_in_match = lolapi.get_teams([event.match.team_one_id, event.match.team_two_id])

        # Gets the teams involved in the match
        for api_team_data in api_teams_in_match:
            if api_team_data['name'] == 'TBD':
                match_team = MatchTeam(name='TBD', image=None, match=new_match)
                db.session.add(match_team)
                continue

            canonical_team = get_or_create_canonical_team(api_team_data, event.league, 'LoL')
            match_team = MatchTeam(name=canonical_team.name, image=canonical_team.image, match=new_match,
                                   canonical_team=canonical_team)
            db.session.add(match_team)

            # Create MatchPlayers
            for api_player_data in api_team_data.get('players', []):
                canonical_player = get_or_create_canonical_player(api_player_data, event.league, 'LoL', canonical_team)
                if canonical_player:
                    match_player = MatchPlayer(name=canonical_player.name, role=api_player_data['role'],
                                               image=canonical_player.image, match_team=match_team,
                                               canonical_player=canonical_player)
                    db.session.add(match_player)
                    current_match_players_map[canonical_player.external_id] = match_player

        # Adds the existing games
        if not event.match.games:
            for api_game_data in match_details_api.games:
                if api_game_data.state != 'completed' and api_game_data.state != 'finished':
                    continue
                # Create Game Obj
                game_obj = Game(
                    game_id=api_game_data.game_id
                )
                game_obj.match = new_match
                db.session.add(game_obj)

                # Create blue GameTeam
                blue_canonical_team_for_game = CanonicalTeam.query.filter_by(
                    external_id=api_game_data.blue_team.id).first()
                blue_game_team = GameTeam(
                    team_id=api_game_data.blue_team.id,
                    team_name=blue_canonical_team_for_game.name,
                )
                blue_game_team.game = game_obj
                blue_game_team.canonical_team = blue_canonical_team_for_game
                db.session.add(blue_game_team)

                # Create red GameTeam
                red_canonical_team_for_game = CanonicalTeam.query.filter_by(
                    external_id=api_game_data.red_team.id).first()
                red_game_team = GameTeam(
                    team_id=api_game_data.red_team.id,
                    team_name=red_canonical_team_for_game.name,
                )
                red_game_team.game = game_obj
                red_game_team.canonical_team = red_canonical_team_for_game
                db.session.add(red_game_team)

                # Create GamePlayers
                for p_id, playerStats in api_game_data.participants.items():
                    if p_id < 6:
                        canonical_team_for_game = blue_canonical_team_for_game
                        game_team = blue_game_team
                    else:
                        canonical_team_for_game = red_canonical_team_for_game
                        game_team = red_game_team

                    # Creates player_data for this specific player
                    player_data_for_creation = {
                        'id': playerStats.id,
                        'summonerName': playerStats.name,
                        'role': playerStats.role,
                        'image': None
                    }
                    # Attempt to retrieve an existing canonical_player
                    # Or create a new canonical_player
                    canonical_player_for_stats = get_or_create_canonical_player(
                        player_data_for_creation,
                        event.league,
                        'LoL',
                        team_to_associate_if_new=canonical_team_for_game
                    )
                    # Pair the canonical_player with the MatchPlayer in the map
                    match_player_for_stats = current_match_players_map.get(
                        canonical_player_for_stats.external_id)
                    if not match_player_for_stats:
                        # If the current Game player is not a MatchPlayer
                        target_match_team_for_sub = None
                        for mt_in_match in new_match.match_teams:
                            # Iterate over MatchTeams already created for this match
                            # Look for the id that is associated with this MatchTeam
                            if mt_in_match.canonical_team_id == canonical_team_for_game.id or \
                                    (
                                            mt_in_match.canonical_team and mt_in_match.canonical_team.id == canonical_team_for_game.id):
                                target_match_team_for_sub = mt_in_match
                                break
                        # If successfully found the MatchTeam, create a MatchPlayer for the sub
                        if target_match_team_for_sub:
                            match_player_for_stats = MatchPlayer(
                                name=canonical_player_for_stats.name,
                                role=playerStats.role,
                                image=canonical_player_for_stats.image,
                            )
                            match_player_for_stats.match_team = target_match_team_for_sub
                            match_player_for_stats.canonical_player = canonical_player_for_stats
                            db.session.add(match_player_for_stats)
                            current_match_players_map[
                                str(canonical_player_for_stats.external_id)] = match_player_for_stats
                            current_app.logger.info(
                                f"Created MatchPlayer for substitute {canonical_player_for_stats.name} in MatchTeam {target_match_team_for_sub.name}")
                        else:
                            current_app.logger.error(
                                f"Could not find MatchTeam for substitute player {canonical_player_for_stats.name} (associated with CTeam {canonical_team_for_game.name}) in Match for Event PK {event.id}. Skipping GPP.")
                            continue
                    db.session.flush()
                    # Add a player's stats for a game and pair it to the MatchPlayer and CanonicalPlayer

                    player_stats_dict = {
                        'p_id': playerStats.p_id,
                        'id': playerStats.id,
                        'name': canonical_player_for_stats.name,
                        'role': playerStats.role,
                        'champion': playerStats.champion,
                        'gold': playerStats.gold,
                        'level': playerStats.level,
                        'kills': playerStats.kills,
                        'deaths': playerStats.deaths,
                        'assists': playerStats.assists,
                        'creeps': playerStats.creeps
                    }
                    gpp = GamePlayerPerformance(stats=player_stats_dict,
                                                canonical_player_id=canonical_player_for_stats.id,
                                                match_player_id=match_player_for_stats.id
                                                )
                    match_player = match_player_for_stats if match_player_for_stats else None
                    game_team.gamePlayers.append(gpp)
                    canonical_player_for_stats.game_participations.append(
                        gpp)
                    if match_player_for_stats and hasattr(match_player_for_stats, 'game_stats'):
                        match_player_for_stats.game_stats.append(gpp)
                    db.session.add(gpp)

        db.session.commit()
        current_app.logger.info(f"✅ Successfully seeded match for event: {event.match_id} (Event PK: {event.id})")
        time.sleep(0.1)
    except Exception as e:
        current_app.logger.error(f"❌ Failed to seed match for event {event.id}. Error: {e}", exc_info=True)
        db.session.rollback()
        # Retry the task after a delay
        # raise self.retry(exc=e, countdown=60)

def seed_mlb_matches(event):
    try:
        # Could use populate unstarted event and populate completed event helpers here
        # They would have to return and share info between them
        today = datetime.today()
        mlb_current_match_players_map = {}
        # Get the MLB API Match object
        match_details = mlbapi.get_match(event.match_id)
        # Create the Match table entry
        new_match = Match(team_one_id=str(match_details.home_team.id), team_two_id=str(match_details.away_team.id))
        event.match = new_match
        db.session.add(new_match)

        # Create the Match Teams
        home_team_api = mlbapi.get_team(match_details.home_team.id, today.strftime("%Y-%m-%d"))
        away_team_api = mlbapi.get_team(match_details.away_team.id, today.strftime("%Y-%m-%d"))
        home_canonical_team = get_or_create_canonical_team(home_team_api, event.league, 'MLB',
                                                           id=str(match_details.home_team.id),
                                                           name=match_details.home_team.name,
                                                           image=f"https://www.mlbstatic.com/team-logos/team-cap-on-dark/{match_details.home_team.id}.svg")
        away_canonical_team = get_or_create_canonical_team(away_team_api, event.league, 'MLB',
                                                           id=str(match_details.away_team.id),
                                                           name=match_details.away_team.name,
                                                           image=f"https://www.mlbstatic.com/team-logos/team-cap-on-dark/{match_details.away_team.id}.svg")
        home_mt = MatchTeam(name=home_canonical_team.name, image=home_canonical_team.image, match=new_match,
                            canonical_team=home_canonical_team)
        away_mt = MatchTeam(name=away_canonical_team.name, image=away_canonical_team.image, match=new_match,
                            canonical_team=away_canonical_team)
        db.session.add(home_mt)
        db.session.add(away_mt)

        # Create MatchPlayers
        for api_player_data in home_team_api:
            canonical_player = get_or_create_canonical_player(api_player_data, event.league, 'MLB',
                                                              team_to_associate_if_new=home_canonical_team,
                                                              external_id=str(api_player_data['person']['id']),
                                                              name=api_player_data['person']['fullName'],
                                                              role=api_player_data['position']['name'],
                                                              image=f"https://img.mlbstatic.com/mlb-photos/image/upload/w_213,d_people:generic:headshot:silo:current.png,q_auto:best,f_auto/v1/people/{api_player_data['person']['id']}/headshot/67/current")
            if canonical_player:
                match_player = MatchPlayer(name=canonical_player.name, role=canonical_player.role,
                                           image=canonical_player.image, match_team=home_mt,
                                           canonical_player=canonical_player)
                db.session.add(match_player)
                mlb_current_match_players_map[canonical_player.external_id] = match_player
        for api_player_data in away_team_api:
            canonical_player = get_or_create_canonical_player(api_player_data, event.league, 'MLB',
                                                              team_to_associate_if_new=away_canonical_team,
                                                              external_id=str(api_player_data['person']['id']),
                                                              name=api_player_data['person']['fullName'],
                                                              role=api_player_data['position']['name'],
                                                              image=f"https://img.mlbstatic.com/mlb-photos/image/upload/w_213,d_people:generic:headshot:silo:current.png,q_auto:best,f_auto/v1/people/{api_player_data['person']['id']}/headshot/67/current")
            if canonical_player:
                match_player = MatchPlayer(name=canonical_player.name, role=canonical_player.role,
                                           image=canonical_player.image, match_team=away_mt,
                                           canonical_player=canonical_player)
                db.session.add(match_player)
                mlb_current_match_players_map[canonical_player.external_id] = match_player

        # Create the Game
        game_obj = Game(game_id=str(match_details.id))
        game_obj.match = new_match
        db.session.add(game_obj)

        # Create the GameTeams
        home_game_canonical_team = CanonicalTeam.query.filter_by(external_id=str(match_details.home_team.id)).first()
        away_game_canonical_team = CanonicalTeam.query.filter_by(external_id=str(match_details.away_team.id)).first()
        home_game_team = GameTeam(
            team_id=str(home_game_canonical_team.external_id),
            team_name=home_game_canonical_team.name,
        )
        home_game_team.game = game_obj
        home_game_team.canonical_team = home_game_canonical_team
        db.session.add(home_game_team)

        away_game_team = GameTeam(
            team_id=str(away_game_canonical_team.external_id),
            team_name=away_game_canonical_team.name,
        )
        away_game_team.game = game_obj
        away_game_team.canonical_team = away_game_canonical_team
        db.session.add(away_game_team)

        # Create GamePlayers
        # Will refactor later to reduce code length
        home_team_players = match_details.home_team.players
        away_team_players = match_details.away_team.players
        for player_id, player_data in home_team_players.items():
            player_data_for_creation = {
            }
            canonical_player_for_stats = get_or_create_canonical_player(
                player_data_for_creation,
                event.league,
                'MLB',
                team_to_associate_if_new=home_game_canonical_team,
                external_id=str(player_data.id),
                name=player_data.name,
                role=player_data.position,
                image=f"https://img.mlbstatic.com/mlb-photos/image/upload/w_213,d_people:generic:headshot:silo:current.png,q_auto:best,f_auto/v1/people/{player_data.id}/headshot/67/current"
            )
            match_player_for_stats = mlb_current_match_players_map.get(
                canonical_player_for_stats.external_id)
            if not match_player_for_stats:
                target_match_team_for_sub = None
                for mt_in_match in new_match.match_teams:
                    if mt_in_match.canonical_team_id == home_game_canonical_team.id or \
                            (
                                    mt_in_match.canonical_team and mt_in_match.canonical_team.id == home_game_canonical_team.id):
                        target_match_team_for_sub = mt_in_match
                        break
                if target_match_team_for_sub:
                    match_player_for_stats = MatchPlayer(
                        name=canonical_player_for_stats.name,
                        role=canonical_player_for_stats.role,
                        image=canonical_player_for_stats.image,
                    )
                    match_player_for_stats.match_team = target_match_team_for_sub
                    match_player_for_stats.canonical_player = canonical_player_for_stats
                    db.session.add(match_player_for_stats)
                    mlb_current_match_players_map[
                        str(canonical_player_for_stats.external_id)] = match_player_for_stats
                    current_app.logger.info("Created MatchPlayer sub in MLB")
                else:
                    current_app.logger.info("MatchPlayer sub not found, skipping")
                    continue
            db.session.flush()

            player_stats_dict = {
                'name': player_data.name,
                'position': player_data.position,
                'gameStatus': player_data.gameStatus,
            }
            if hasattr(player_data, 'batting_stats'):
                player_stats_dict['batting_stats'] = player_data.batting_stats
            if hasattr(player_data, 'pitching_stats'):
                player_stats_dict['pitching_stats'] = player_data.pitching_stats
            if hasattr(player_data, 'battingOrder'):
                player_stats_dict['battingOrder'] = player_data.battingOrder
            if hasattr(player_data, 'summary'):
                player_stats_dict['summary'] = player_data.summary
            gpp = GamePlayerPerformance(stats=player_stats_dict,
                                        canonical_player_id=canonical_player_for_stats.id,
                                        match_player_id=match_player_for_stats.id
                                        )
            match_player = match_player_for_stats if match_player_for_stats else None
            home_game_team.gamePlayers.append(gpp)
            canonical_player_for_stats.game_participations.append(gpp)
            if match_player is not None:
                match_player.game_stats.append(gpp)
            db.session.add(gpp)

        for player_id, player_data in away_team_players.items():
            player_data_for_creation = {
            }
            canonical_player_for_stats = get_or_create_canonical_player(
                player_data_for_creation,
                event.league,
                'MLB',
                team_to_associate_if_new=away_game_canonical_team,
                external_id=str(player_data.id),
                name=player_data.name,
                role=player_data.position,
                image=f"https://img.mlbstatic.com/mlb-photos/image/upload/w_213,d_people:generic:headshot:silo:current.png,q_auto:best,f_auto/v1/people/{player_data.id}/headshot/67/current"
            )
            match_player_for_stats = mlb_current_match_players_map.get(
                canonical_player_for_stats.external_id)
            if not match_player_for_stats:
                target_match_team_for_sub = None
                for mt_in_match in new_match.match_teams:
                    if mt_in_match.canonical_team_id == away_game_canonical_team.id or \
                            (
                                    mt_in_match.canonical_team and mt_in_match.canonical_team.id == away_game_canonical_team.id):
                        target_match_team_for_sub = mt_in_match
                        break
                if target_match_team_for_sub:
                    match_player_for_stats = MatchPlayer(
                        name=canonical_player_for_stats.name,
                        role=canonical_player_for_stats.role,
                        image=canonical_player_for_stats.image,
                    )
                    match_player_for_stats.match_team = target_match_team_for_sub
                    match_player_for_stats.canonical_player = canonical_player_for_stats
                    db.session.add(match_player_for_stats)
                    mlb_current_match_players_map[
                        str(canonical_player_for_stats.external_id)] = match_player_for_stats
                    current_app.logger.info("Created MatchPlayer sub in MLB")
                else:
                    current_app.logger.info("MatchPlayer sub not found, skipping")
                    continue
            db.session.flush()

            player_stats_dict = {
                'name': player_data.name,
                'position': player_data.position,
                'gameStatus': player_data.gameStatus,
            }
            if hasattr(player_data, 'batting_stats'):
                player_stats_dict['batting_stats'] = player_data.batting_stats
            if hasattr(player_data, 'pitching_stats'):
                player_stats_dict['pitching_stats'] = player_data.pitching_stats
            if hasattr(player_data, 'battingOrder'):
                player_stats_dict['battingOrder'] = player_data.battingOrder
            if hasattr(player_data, 'summary'):
                player_stats_dict['summary'] = player_data.summary
            gpp = GamePlayerPerformance(stats=player_stats_dict,
                                        canonical_player_id=canonical_player_for_stats.id,
                                        match_player_id=match_player_for_stats.id
                                        )
            match_player = match_player_for_stats if match_player_for_stats else None
            away_game_team.gamePlayers.append(gpp)
            canonical_player_for_stats.game_participations.append(gpp)
            if match_player is not None:
                match_player.game_stats.append(gpp)
            db.session.add(gpp)

        db.session.commit()
        current_app.logger.info(
            f"✅ Successfully seeded match for event: {event.match_id} (Event PK: {event.id}) in MLB")
        time.sleep(0.1)

    except Exception as e:
        current_app.logger.error(f"❌ Failed to seed match for event {event.id}. Error: {e} in MLB", exc_info=True)
        db.session.rollback()
        # Retry the task after a delay
        # raise self.retry(exc=e, countdown=60)

# --- Stage 3 Task ---
@celery.task(name='tasks.seed_match_for_event', bind=True)
def seed_match_for_event_task(self, event_id):
    """Seeds the detailed match data for a single event."""
    event = Event.query.get(event_id)
    if not event:
        current_app.logger.warning(f"Skipping match seed: Event ID {event_id} not found.")
        return
    if event.match:
        current_app.logger.info(f"Skipping match seed: Event {event.match_id} already has a match.")
        return

    current_app.logger.info(f"Starting to seed match for event: {event.match_id} (Event PK: {event.id})")

    if event.league.name != 'MLB':
        seed_lol_matches(event)
    else:
        seed_mlb_matches(event)

@celery.task
def cleanup_unused_match_players():
    current_app.logger.info("Starting cleanup job for unused MatchPlayer records...")

    # Query all players that have some stats
    players_with_stats_query = db.session.query(GamePlayerPerformance.match_player_id).distinct()
    players_with_stats_ids = {row.match_player_id for row in players_with_stats_query}
    current_app.logger.info(f"Found {len(players_with_stats_ids)} MatchPlayers that have game stats.")

    # Query all players that are in a completed event
    all_players_in_completed_matches_query = db.session.query(MatchPlayer.id).join(
        MatchPlayer.match_team
    ).join(
        MatchTeam.match
    ).join(
        Match.event
    ).filter(
        Event.state == 'completed'
    )
    all_players_in_completed_matches_ids = {row.id for row in all_players_in_completed_matches_query}
    current_app.logger.info(
        f"Found {len(all_players_in_completed_matches_ids)} total MatchPlayer IDs in completed events.")

    ids_to_delete = all_players_in_completed_matches_ids - players_with_stats_ids

    if not ids_to_delete:
        current_app.logger.info("No unused MatchPlayer records found to delete. Cleanup complete.")
        return

    current_app.logger.warning(f"Identified {len(ids_to_delete)} unused MatchPlayer records to delete.")

    try:
        delete_query = db.session.query(MatchPlayer).filter(MatchPlayer.id.in_(ids_to_delete))
        deleted_count = delete_query.delete(synchronize_session=False)
        db.session.commit()
        current_app.logger.info(f"Successfully bulk deleted {deleted_count} unused MatchPlayer records.")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"An error occurred during MatchPlayer bulk cleanup: {e}", exc_info=True)

# currently only LoL events can have TBD teams
def update_TBD_event(event:Event):
    match_details = lolapi.get_match(event.match_id)
    if match_details is None:
        return
    event.match.team_one_id = match_details.team_ids[0]
    event.match.team_two_id = match_details.team_ids[1]
    api_teams_in_match = lolapi.get_teams([event.match.team_one_id, event.match.team_two_id])
    event.team_one = api_teams_in_match[0]['name']
    event.team_two = api_teams_in_match[1]['name']
    i = 0
    for api_team_data in api_teams_in_match:
        if event.match.match_teams[i].name != api_team_data['name']:
            canonical_team = get_or_create_canonical_team(api_team_data, event.league)
            match_team = event.match.match_teams[i]
            match_team.name = canonical_team.name
            match_team.image = canonical_team.image
            match_team.match = event.match
            match_team.canonical_team = canonical_team
            for match_player in match_team.match_players:
                db.session.delete(match_player)
            for api_player_data in api_team_data.get('players', []):
                canonical_player = get_or_create_canonical_player(api_player_data, event.league, canonical_team)
                if canonical_player is None:
                    continue
                match_player = MatchPlayer(
                    name=canonical_player.name,
                    role=api_player_data['role'],
                    image=canonical_player.image,
                )
                match_player.match_team = match_team
                match_player.canonical_player = canonical_player
                db.session.add(match_player)
        i += 1
    db.session.commit()
    current_app.logger.info(f"Finished updating TBD event with ID {event.id} in league {event.league.name}")

def store_final_lol_results_in_db(final_match_object, event: Event):
    try:
        current_match_players_map = {}
        for match_team in event.match.match_teams:
            for match_player in match_team.match_players:
                current_match_players_map[match_player.canonical_player.external_id] = match_player
        if not event.match.games:
            for api_game_data in final_match_object.games:
                if api_game_data.state != 'completed' and api_game_data.state != 'finished':
                    continue
                # Create Game Obj
                game_obj = Game(
                    game_id=api_game_data.game_id
                )
                game_obj.match = final_match_object
                db.session.add(game_obj)

                # Create blue GameTeam
                blue_canonical_team_for_game = CanonicalTeam.query.filter_by(
                    external_id=api_game_data.blue_team.id).first()
                blue_game_team = GameTeam(
                    team_id=api_game_data.blue_team.id,
                    team_name=blue_canonical_team_for_game.name,
                )
                blue_game_team.game = game_obj
                blue_game_team.canonical_team = blue_canonical_team_for_game
                db.session.add(blue_game_team)

                # Create red GameTeam
                red_canonical_team_for_game = CanonicalTeam.query.filter_by(
                    external_id=api_game_data.red_team.id).first()
                red_game_team = GameTeam(
                    team_id=api_game_data.red_team.id,
                    team_name=red_canonical_team_for_game.name,
                )
                red_game_team.game = game_obj
                red_game_team.canonical_team = red_canonical_team_for_game
                db.session.add(red_game_team)

                # Create GamePlayers
                for p_id, playerStats in api_game_data.participants.items():
                    if p_id < 6:
                        canonical_team_for_game = blue_canonical_team_for_game
                        game_team = blue_game_team
                    else:
                        canonical_team_for_game = red_canonical_team_for_game
                        game_team = red_game_team

                    # Creates player_data for this specific player
                    player_data_for_creation = {
                        'id': playerStats.id,
                        'summonerName': playerStats.name,
                        'role': playerStats.role,
                        'image': None
                    }
                    # Attempt to retrieve an existing canonical_player
                    # Or create a new canonical_player
                    canonical_player_for_stats = get_or_create_canonical_player(
                        player_data_for_creation,
                        event.league,
                        'LoL',
                        team_to_associate_if_new=canonical_team_for_game
                    )
                    # Pair the canonical_player with the MatchPlayer in the map
                    match_player_for_stats = current_match_players_map.get(
                        canonical_player_for_stats.external_id)
                    if not match_player_for_stats:
                        # If the current Game player is not a MatchPlayer
                        target_match_team_for_sub = None
                        for mt_in_match in final_match_object.match_teams:
                            # Iterate over MatchTeams already created for this match
                            # Look for the id that is associated with this MatchTeam
                            if mt_in_match.canonical_team_id == canonical_team_for_game.id or \
                                    (
                                            mt_in_match.canonical_team and mt_in_match.canonical_team.id == canonical_team_for_game.id):
                                target_match_team_for_sub = mt_in_match
                                break
                        # If successfully found the MatchTeam, create a MatchPlayer for the sub
                        if target_match_team_for_sub:
                            match_player_for_stats = MatchPlayer(
                                name=canonical_player_for_stats.name,
                                role=playerStats.role,
                                image=canonical_player_for_stats.image,
                            )
                            match_player_for_stats.match_team = target_match_team_for_sub
                            match_player_for_stats.canonical_player = canonical_player_for_stats
                            db.session.add(match_player_for_stats)
                            current_match_players_map[
                                str(canonical_player_for_stats.external_id)] = match_player_for_stats
                            current_app.logger.info(
                                f"Created MatchPlayer for substitute {canonical_player_for_stats.name} in MatchTeam {target_match_team_for_sub.name}")
                        else:
                            current_app.logger.error(
                                f"Could not find MatchTeam for substitute player {canonical_player_for_stats.name} (associated with CTeam {canonical_team_for_game.name}) in Match for Event PK {event.id}. Skipping GPP.")
                            continue
                    db.session.flush()
                    # Add a player's stats for a game and pair it to the MatchPlayer and CanonicalPlayer

                    player_stats_dict = {
                        'p_id': playerStats.p_id,
                        'id': playerStats.id,
                        'name': canonical_player_for_stats.name,
                        'role': playerStats.role,
                        'champion': playerStats.champion,
                        'gold': playerStats.gold,
                        'level': playerStats.level,
                        'kills': playerStats.kills,
                        'deaths': playerStats.deaths,
                        'assists': playerStats.assists,
                        'creeps': playerStats.creeps
                    }
                    gpp = GamePlayerPerformance(stats=player_stats_dict,
                                                canonical_player_id=canonical_player_for_stats.id,
                                                match_player_id=match_player_for_stats.id
                                                )
                    match_player = match_player_for_stats if match_player_for_stats else None
                    game_team.gamePlayers.append(gpp)
                    canonical_player_for_stats.game_participations.append(
                        gpp)
                    if match_player_for_stats and hasattr(match_player_for_stats, 'game_stats'):
                        match_player_for_stats.game_stats.append(gpp)
                    db.session.add(gpp)
        event.state = 'completed'
        db.session.commit()
        current_app.logger.info(f"✅ Successfully stored match for event: {event.match_id} (Event PK: {event.id})")
    except Exception as e:
        current_app.logger.error(f"❌ Failed to store match for event {event.id}. Error: {e}", exc_info=True)
        db.session.rollback()

def store_final_mlb_results_in_db(final_match_object, event:Event):
    try:
        mlb_current_match_players_map = {}
        # Find all MatchPlayers for the Match
        # Store in a Map to later associate with a GamePlayer
        for match_team in event.match.match_teams:
            for match_player in match_team.match_players:
                mlb_current_match_players_map[match_player.canonical_player.external_id] = match_player
        # Get the Game
        new_match = event.match
        game_obj = event.match.games[0]

        # Get the GameTeams
        home_game_canonical_team = CanonicalTeam.query.filter_by(external_id=str(final_match_object.home_team.id)).first()
        away_game_canonical_team = CanonicalTeam.query.filter_by(external_id=str(final_match_object.away_team.id)).first()
        home_game_team = GameTeam.query.filter_by(game=event.match.games[0], canonical_team=home_game_canonical_team).first()
        away_game_team = GameTeam.query.filter_by(game=event.match.games[0], canonical_team=away_game_canonical_team).first()
        if not home_game_team and not away_game_team:
            home_game_team = GameTeam(
                team_id=str(home_game_canonical_team.external_id),
                team_name=home_game_canonical_team.name,
                image=f"https://www.mlbstatic.com/team-logos/team-cap-on-dark/{final_match_object.home_team.id}.svg"
            )
            home_game_team.game = game_obj
            home_game_team.canonical_team = home_game_canonical_team
            db.session.add(home_game_team)
            away_game_team = GameTeam(
                team_id=str(away_game_canonical_team.external_id),
                team_name=away_game_canonical_team.name,
                image=f"https://www.mlbstatic.com/team-logos/team-cap-on-dark/{final_match_object.away_team.id}.svg"
            )
            away_game_team.game = game_obj
            away_game_team.canonical_team = away_game_canonical_team
            db.session.add(away_game_team)

        # Create GamePlayers
        home_team_players = final_match_object.home_team.players
        away_team_players = final_match_object.away_team.players
        for player_id, player_data in home_team_players.items():
            player_data_for_creation = {
            }
            canonical_player_for_stats = get_or_create_canonical_player(
                player_data_for_creation,
                event.league,
                'MLB',
                team_to_associate_if_new=home_game_canonical_team,
                external_id=str(player_data.id),
                name=player_data.name,
                role=player_data.position,
                image=f"https://img.mlbstatic.com/mlb-photos/image/upload/w_213,d_people:generic:headshot:silo:current.png,q_auto:best,f_auto/v1/people/{player_data.id}/headshot/67/current"
            )
            match_player_for_stats = mlb_current_match_players_map.get(
                canonical_player_for_stats.external_id)
            if not match_player_for_stats:
                target_match_team_for_sub = None
                for mt_in_match in new_match.match_teams:
                    if mt_in_match.canonical_team_id == home_game_canonical_team.id or \
                            (
                                    mt_in_match.canonical_team and mt_in_match.canonical_team.id == home_game_canonical_team.id):
                        target_match_team_for_sub = mt_in_match
                        break
                if target_match_team_for_sub:
                    match_player_for_stats = MatchPlayer(
                        name=canonical_player_for_stats.name,
                        role=canonical_player_for_stats.role,
                        image=canonical_player_for_stats.image,
                    )
                    match_player_for_stats.match_team = target_match_team_for_sub
                    match_player_for_stats.canonical_player = canonical_player_for_stats
                    db.session.add(match_player_for_stats)
                    mlb_current_match_players_map[
                        str(canonical_player_for_stats.external_id)] = match_player_for_stats
                    current_app.logger.info("Created MatchPlayer sub in MLB")
                else:
                    current_app.logger.info("MatchPlayer sub not found, skipping")
                    continue
            db.session.flush()
            gpp = GamePlayerPerformance.query.filter_by(gameTeam=home_game_team, canonical_player=canonical_player_for_stats)
            player_stats_dict = {
                'name': player_data.name,
                'position': player_data.position,
                'gameStatus': player_data.gameStatus,
            }
            if hasattr(player_data, 'batting_stats'):
                player_stats_dict['batting_stats'] = player_data.batting_stats
            if hasattr(player_data, 'pitching_stats'):
                player_stats_dict['pitching_stats'] = player_data.pitching_stats
            if hasattr(player_data, 'battingOrder'):
                player_stats_dict['battingOrder'] = player_data.battingOrder
            if hasattr(player_data, 'summary'):
                player_stats_dict['summary'] = player_data.summary
            if not gpp:
                gpp = GamePlayerPerformance(stats=player_stats_dict,
                                            canonical_player_id=canonical_player_for_stats.id,
                                            match_player_id=match_player_for_stats.id
                                            )
                match_player = match_player_for_stats if match_player_for_stats else None
                home_game_team.gamePlayers.append(gpp)
                canonical_player_for_stats.game_participations.append(gpp)
                if match_player is not None:
                    match_player.game_stats.append(gpp)
                db.session.add(gpp)
            else:
                gpp.stats = player_stats_dict

        for player_id, player_data in away_team_players.items():
            player_data_for_creation = {
            }
            canonical_player_for_stats = get_or_create_canonical_player(
                player_data_for_creation,
                event.league,
                'MLB',
                team_to_associate_if_new=away_game_canonical_team,
                external_id=str(player_data.id),
                name=player_data.name,
                role=player_data.position,
                image=f"https://img.mlbstatic.com/mlb-photos/image/upload/w_213,d_people:generic:headshot:silo:current.png,q_auto:best,f_auto/v1/people/{player_data.id}/headshot/67/current"
            )
            match_player_for_stats = mlb_current_match_players_map.get(
                canonical_player_for_stats.external_id)
            if not match_player_for_stats:
                target_match_team_for_sub = None
                for mt_in_match in new_match.match_teams:
                    if mt_in_match.canonical_team_id == away_game_canonical_team.id or \
                            (
                                    mt_in_match.canonical_team and mt_in_match.canonical_team.id == away_game_canonical_team.id):
                        target_match_team_for_sub = mt_in_match
                        break
                if target_match_team_for_sub:
                    match_player_for_stats = MatchPlayer(
                        name=canonical_player_for_stats.name,
                        role=canonical_player_for_stats.role,
                        image=canonical_player_for_stats.image,
                    )
                    match_player_for_stats.match_team = target_match_team_for_sub
                    match_player_for_stats.canonical_player = canonical_player_for_stats
                    db.session.add(match_player_for_stats)
                    mlb_current_match_players_map[
                        str(canonical_player_for_stats.external_id)] = match_player_for_stats
                    current_app.logger.info("Created MatchPlayer sub in MLB")
                else:
                    current_app.logger.info("MatchPlayer sub not found, skipping")
                    continue
            db.session.flush()
            gpp = GamePlayerPerformance.query.filter_by(gameTeam=away_game_team,
                                                        canonical_player=canonical_player_for_stats)
            player_stats_dict = {
                'name': player_data.name,
                'position': player_data.position,
                'gameStatus': player_data.gameStatus,
            }
            if hasattr(player_data, 'batting_stats'):
                player_stats_dict['batting_stats'] = player_data.batting_stats
            if hasattr(player_data, 'pitching_stats'):
                player_stats_dict['pitching_stats'] = player_data.pitching_stats
            if hasattr(player_data, 'battingOrder'):
                player_stats_dict['battingOrder'] = player_data.battingOrder
            if hasattr(player_data, 'summary'):
                player_stats_dict['summary'] = player_data.summary
            if not gpp:
                gpp = GamePlayerPerformance(stats=player_stats_dict,
                                            canonical_player_id=canonical_player_for_stats.id,
                                            match_player_id=match_player_for_stats.id
                                            )
                match_player = match_player_for_stats if match_player_for_stats else None
                away_game_team.gamePlayers.append(gpp)
                canonical_player_for_stats.game_participations.append(gpp)
                if match_player is not None:
                    match_player.game_stats.append(gpp)
                db.session.add(gpp)
            else:
                gpp.stats = player_stats_dict
        event.state = 'completed'
        db.session.commit()
        current_app.logger.info(f"✅ Successfully stored match for event: {event.match_id} (Event PK: {event.id})")
    except Exception as e:
        current_app.logger.error(f"❌ Failed to store match for event {event.id}. Error: {e} in MLB", exc_info=True)
        db.session.rollback()

def handle_baseball_update(event:Event):
    redis_key = f"match_state:{event.match_id}"
    lock_key = f"polling_lock:{event.match_id}"
    try:
        # Initial Creation
        current_app.logger.info(f"POLLER: Creating initial state for match {event.match_id}...")
        match_object = mlbapi.get_match(int(event.match_id))
        if not match_object:
            current_app.logger.error(f"POLLER: Failed to create initial match object for {event.match_id}")
            return
        # --- Find all users tracking this match ---
        # This query gets the user IDs for everyone tracking this event.
        user_ids_tracking_this_match = [
            item.user_id for item in UserTrackedItem.query.filter_by(event_id=event.id).all()
        ]

        cache.set(redis_key, match_object, timeout=6 * 60 * 60)  # Store for 6 hours

        # The Update Loop
        while match_object and match_object.state != 'Final':
            current_app.logger.info(f"POLLER: Polling for updates on match {event.match_id}...")
            latest_match_state = cache.get(redis_key)
            if not latest_match_state:
                current_app.logger.warning(f"POLLER: Match object for {event.match_id} disappeared from cache. Stopping poll.")
                break

            mlbapi.update_match(match_object)
            cache.set(redis_key, match_object, timeout=6 * 60 * 60)

            if user_ids_tracking_this_match:
                payload = json.dumps(match_object.to_dict())
                for user_id in user_ids_tracking_this_match:
                    channel = f"user-updates:{user_id}"
                    redis_client.publish(channel, payload)
            time.sleep(20)

        # Finalization
        current_app.logger.info(f"POLLER: Polling finished for match {event.match_id}. Storing final results.")
        final_data = cache.get(redis_key)
        if final_data:
            store_final_mlb_results_in_db(final_data, event)

    finally:
        # Clean up Redis keys when the task is done
        current_app.logger.info(f"POLLER: Cleaning up Redis keys for match {event.match_id}.")
        cache.delete(redis_key)
        cache.delete(lock_key)

def handle_lol_update(event:Event):
    redis_key = f"match_state:{event.match_id}"
    lock_key = f"polling_lock:{event.match_id}"
    try:
        # Initial Creation
        current_app.logger.info(f"POLLER: Creating initial state for match {event.match_id}...")
        match_object = lolapi.get_match(event.match_id)
        if not match_object:
            current_app.logger.error(f"POLLER: Failed to create initial match object for {event.match_id}")
            return
        user_ids_tracking_this_match = [
            item.user_id for item in UserTrackedItem.query.filter_by(event_id=event.id).all()
        ]

        cache.set(redis_key, match_object, timeout=6 * 60 * 60)  # Store for 6 hours

        # The Update Loop
        while match_object and match_object.state != 'completed':
            current_app.logger.info(f"POLLER: Polling for updates on match {event.match_id}...")
            latest_match_state = cache.get(redis_key)
            if not latest_match_state:
                current_app.logger.warning(
                    f"POLLER: Match object for {event.match_id} disappeared from cache. Stopping poll.")
                break

            lolapi.update_match(match_object)
            lolapi.update_match_state(match_object)
            cache.set(redis_key, match_object, timeout=6 * 60 * 60)

            if user_ids_tracking_this_match:
                payload = json.dumps(match_object.to_dict())
                for user_id in user_ids_tracking_this_match:
                    channel = f"user-updates:{user_id}"
                    redis_client.publish(channel, payload)
            time.sleep(20)

        # Finalization
        current_app.logger.info(f"POLLER: Polling finished for match {event.match_id}. Storing final results.")
        final_data = cache.get(redis_key)
        if final_data:
            store_final_lol_results_in_db(final_data, event)

    finally:
        # Clean up Redis keys when the task is done
        current_app.logger.info(f"POLLER: Cleaning up Redis keys for match {event.match_id}.")
        cache.delete(redis_key)
        cache.delete(lock_key)

@celery.task(bind=True)
def poll_live_match_data(self, event_id):
    event = Event.query.get(event_id)
    sport = event.league.sport.name
    if sport == 'Baseball':
        handle_baseball_update(event)
    else:
        handle_lol_update(event)

@celery.task(bind=True)
def start_match_polling_chain(self, event_id):
    """
    Safely starts the polling process for an event.
    - Updates the event state to 'inProgress'.
    - Sets a Redis lock to prevent duplicate polling chains.
    - Kicks off the first run of the 'update_in_progress_match' task.
    This task is idempotent: calling it multiple times for the same active
    event will have no negative effect.
    """
    try:
        event = Event.query.get(event_id)
        if not event:
            current_app.logger.error(f"Task 'start_match_polling_chain' could not find event {event_id}.")
            return

        lock_key = f"polling_lock_match_{event.match_id}"

        # If a lock already exists, another process has already started this. We can safely exit.
        if cache.get(lock_key):
            current_app.logger.info(f"Polling for match {event.match_id} is already active. Skipping start request.")
            return

        current_app.logger.info(f"Match {event.match_id} is starting. Kicking off polling chain.")

        # 1. Update the event state
        event.state = 'inProgress'
        db.session.commit()

        # 2. Set the lock to prevent other tasks from starting a duplicate chain
        cache.set(lock_key, "locked", timeout=300)  # 5-minute safety timeout

        # 3. Kick off the first run of the actual polling task
        poll_live_match_data.delay(event.id)
    except OperationalError as exc:
        raise self.retry(exc=exc, countdown=60, max_retries=3)

    except Exception as exc:
        current_app.logger.error("NONOperationalError Exception")
        raise

@celery.task(bind=True)
def check_unstarted_events(self):
    try:
        current_app.logger.info("Updating TBD tasks...")
        tbd_events = Event.query.filter(
            Event.state == 'unstarted',
            db.or_(Event.team_one == 'TBD', Event.team_two == 'TBD')
        ).all()

        if tbd_events:
            current_app.logger.info(f"Found {len(tbd_events)} TBD events to update.")
            for event in tbd_events:
                try:
                    update_TBD_event(event)
                except Exception as e:
                    current_app.logger.error(f"Error updating TBD for Event {event.id}: {e}")
                    db.session.rollback()
            db.session.commit()
    except OperationalError as exc:
        raise self.retry(exc=exc, countdown=60, max_retries=3)
    except Exception as exc:
        current_app.logger.error(f"An unexpected error occurred in check_unstarted_events: {exc}", exc_info=True)
        raise

@celery.task(bind=True)
def check_and_start_polling(self):
    try:
        current_app.logger.info("Running task to check all unstarted and in progress events...")
        now = datetime.now(timezone.utc)

        # --- Step 2: Schedule Start Jobs for New/Resolved Events ---
        events_to_start = Event.query.filter(
            db.or_(Event.state == 'unstarted', Event.state == 'inProgress'),
            Event.team_one != 'TBD',
            Event.team_two != 'TBD',
        ).all()
        for event in events_to_start:
            if not event.match_id:
                continue
            if event.start_time_datetime.replace(tzinfo=timezone.utc) > now:
                continue

            lock_key = f"polling_lock:{event.match_id}"

            # Try to acquire a lock. nx=True means set only if it doesn't exist.
            # ex=3600 sets a 1-hour timeout on the lock as a safety measure.
            lock_acquired = redis_client.set(lock_key, "locked", ex=300, nx=True)

            if lock_acquired:
                current_app.logger.info(f"SUPERVISOR: Acquired lock for match {event.match_id}. Kicking off polling task.")
                event.state = 'inProgress'
                poll_live_match_data.delay(event.id)
            else:
                current_app.logger.debug(f"SUPERVISOR: Match {event.match_id} is already being polled. Skipping.")
        current_app.logger.info("Finished scheduling start jobs.")
    except OperationalError as exc:
        raise self.retry(exc=exc, countdown=60, max_retries=3)
    except Exception as exc:
        current_app.logger.error(f"An unexpected error occurred in check_and_start_polling: {exc}", exc_info=True)
        raise
