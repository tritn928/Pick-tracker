import time
from datetime import timedelta
from .celery_app import celery
from app.models import *
from flask import current_app
from lolesports_api.rest_adapter import RestAdapter as LoLRestAdapter
from mlb_api.rest_adapter import RestAdapter as MLBRestAdapter
from app.seeding_helpers import get_or_create_canonical_team, get_or_create_canonical_player

lolapi = LoLRestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')
mlbapi = MLBRestAdapter(hostname='statsapi.mlb.com')

# Will refactor to use this get_api later
def get_api(sport):
    if sport == 'Baseball':
        return mlbapi
    else:
        return lolapi

@celery.task(name='tasks.seed_leagues')
def seed_leagues_task():
    current_app.logger.info("Starting task: seed_leagues_task")

    # ignore = ['LCL', "TFT Esports ", 'LCS', "King's Duel", 'Worlds Qualifying Series', 'LCO', 'LLA', 'CBLOL',
    #           'Arabian League']
    # temp change to only include MSI for testing
    include = ['MSI']
    leagues_list = lolapi.get_leagues()
    lol_to_add = [
        League(name=league['name'], league_id=league['id'], image=league['image'])
        for league in leagues_list if league['name'] in include
    ]
    # Not worrying about separate MLB Leagues for now.
    mlb_to_add = League(name='MLB', league_id='1', image='https://www.mlbstatic.com/team-logos/league-on-dark/1.svg')
    db.session.bulk_save_objects(lol_to_add)
    db.session.add(mlb_to_add)
    db.session.commit()
    current_app.logger.info(f"Finished seeding {len(lol_to_add)} League of Legends leagues.")
    current_app.logger.info(f"Finished seeding 1 MLB League")


# --- Stage 2 Task ---
@celery.task(name='tasks.seed_events_for_league')
def seed_events_for_league_task(league_id):
    """Seeds all events for a single league."""
    league = League.query.get(league_id)
    if not league:
        return

    current_app.logger.info(f"Starting to seed events for league: {league.name}")
    if league.name != 'MLB':
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
    else:
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

            # A single commit at the end of the task for maximum efficiency
            db.session.commit()
            current_app.logger.info(f"✅ Successfully seeded match for event: {event.match_id} (Event PK: {event.id})")
            time.sleep(0.1)
        except Exception as e:
            current_app.logger.error(f"❌ Failed to seed match for event {event_id}. Error: {e}", exc_info=True)
            db.session.rollback()
            # Retry the task after a delay
            #raise self.retry(exc=e, countdown=60)
    else:
        try:
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
            home_canonical_team = get_or_create_canonical_team(home_team_api, event.league, 'MLB', id=str(match_details.home_team.id), name=match_details.home_team.name)
            away_canonical_team = get_or_create_canonical_team(away_team_api, event.league, 'MLB', id=str(match_details.away_team.id), name=match_details.away_team.name)
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
                                                                  image=None)
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
                                                                  image=None)
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
                            image=None
                )
                match_player_for_stats = mlb_current_match_players_map.get(
                    canonical_player_for_stats.external_id)
                if not match_player_for_stats:
                    target_match_team_for_sub = None
                    for mt_in_match in new_match.match_teams:
                        if mt_in_match.canonical_team_id == home_game_canonical_team.id or \
                            (mt_in_match.canonical_team and mt_in_match.canonical_team.id == home_game_canonical_team.id):
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
                            mlb_current_match_players_map[str(canonical_player_for_stats.external_id)] = match_player_for_stats
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
                            image=None
                )
                match_player_for_stats = mlb_current_match_players_map.get(
                    canonical_player_for_stats.external_id)
                if not match_player_for_stats:
                    target_match_team_for_sub = None
                    for mt_in_match in new_match.match_teams:
                        if mt_in_match.canonical_team_id == away_game_canonical_team.id or \
                            (mt_in_match.canonical_team and mt_in_match.canonical_team.id == away_game_canonical_team.id):
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
                            mlb_current_match_players_map[str(canonical_player_for_stats.external_id)] = match_player_for_stats
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
            current_app.logger.error(f"❌ Failed to seed match for event {event_id}. Error: {e} in MLB", exc_info=True)
            db.session.rollback()
            # Retry the task after a delay
            #raise self.retry(exc=e, countdown=60)

