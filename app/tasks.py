from app import app, db
from app.models import *
from lolesports_api.rest_adapter import RestAdapter
from app.scheduler import scheduler
import time
from datetime import datetime, timedelta, timezone
from sqlalchemy import or_

from seed import get_or_create_canonical_player, get_or_create_canonical_team

lolapi = RestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')

# Updates all leagues with new Events
# Kicks off additional jobs to populate the events
def update_leagues():
    with app.app_context():
        app.logger.info("SCHEDULER: Running job to update leagues. Time: " + str(datetime.now(timezone.utc)))
        all_leagues = League.query.all()
        for league in all_leagues:
            event_schedule = lolapi.get_schedule(league_name=league.name, league_id=league.league_id)
            existing_event_match_ids = {event.match_id for event in
                                        Event.query.filter_by(league_id=league.id).with_entities(Event.match_id).all()}
            events_to_add = []
            for event in event_schedule.events:
                if event.match_id not in existing_event_match_ids:
                    app.logger.info(f"SCHEDULER: Found a new event {event.match_id} for league {league.name}")
                    new_event = Event(
                        start_time=event.start_time,
                        strategy=event.strategy,
                        state=event.state,
                        match_id=event.match_id,
                        team_one=event.teams[0].get('name'),
                        team_two=event.teams[1].get('name'),
                        league_id=league.id
                    )
                    events_to_add.append(new_event)
            if events_to_add:
                db.session.add_all(events_to_add)
                db.session.commit()
            time.sleep(.5)
        app.logger.info("SCHEDULER: Finished updating all leagues. Time: " + str(datetime.now(timezone.utc)))
        job_id = f"update_completed_events"
        if not scheduler.get_job(job_id):
            app.logger.info(
                f"SCHEDULER: Kicking off populating completed events without match or games")
            scheduler.add_job(
                id=job_id,
                func=populate_completed_events,
                trigger='date',
                run_date=datetime.now(),
                misfire_grace_time=None
            )
        time.sleep(5)
        job_id = f"populate_unstarted_events"
        if not scheduler.get_job(job_id):
            app.logger.info(
                f"SCHEDULER: Kicking off populating new unstarted events")
            scheduler.add_job(
                id=job_id,
                func=populate_unstarted_events,
                trigger='date',
                run_date=datetime.now(),
                misfire_grace_time=None
            )
        time.sleep(5)

# Populates newly added completed events
def populate_unstarted_events():
    with app.app_context():
        events_to_pop = Event.query.filter(
            Event.state == 'unstarted',
            Event.match == None
        ).all()
        for event in events_to_pop:
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
            db.session.commit()
            app.logger.info(f"SCHEDULER: Updated Unstarted Event {event.id} in league {event.league.name}")
        app.logger.info("SCHEDULER: Finished populating unstarted events")

# Updates unstarted events with TBD teams
def update_TBD_event(event_id):
    with app.app_context():
        event = Event.query.get(event_id)
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
        app.logger.info(f"Finished updating TBD event with ID {event.id} in league {event.league.name}")

# Populates newly added completed events
def populate_completed_events():
    with app.app_context():
        events_to_check = Event.query.filter(
            Event.state == 'completed',
            or_(
                Event.match == None,
                Event.match.has(~Match.games.any())
            )
        ).all()
        for event in events_to_check:
            app.logger.info(f"Processing Event (PK: {event.id}, API MatchID: {event.match_id}) for match creation.")
            match_details_api = lolapi.get_match(event.match_id)
            if event.match is None:
                new_match = Match(
                    event_id=event.id,
                    team_one_id=match_details_api.team_ids[0],
                    team_two_id=match_details_api.team_ids[1]
                )
                event.match = new_match
                db.session.add(new_match)
            else:
                new_match = event.match
            current_match_players_map = {}
            api_teams_in_match = lolapi.get_teams([event.match.team_one_id, event.match.team_two_id])

            # Gets the teams involved in the match
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
                match_team = MatchTeam.query.filter_by(name=canonical_team.name, match_id=new_match.id).first()
                if not match_team:
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
                        current_match_players_map[canonical_player.external_id] = match_player

            # Adds the existing games
            if event.match.games is None:
                for api_game_data in match_details_api.games:
                    # Create Game Obj
                    game_obj = Game(
                        game_id=api_game_data.id
                    )
                    game_obj.match = new_match
                    db.session.add(game_obj)

                    # Create GameTeam
                    for api_team_in_game in api_game_data.teams:
                        canonical_team_for_game = CanonicalTeam.query.filter_by(
                            external_id=api_team_in_game.team_id).first()
                        game_team = GameTeam(
                            team_id=api_team_in_game.team_id,
                            team_name=canonical_team_for_game.name,
                        )
                        game_team.game = game_obj
                        game_team.canonical_team = canonical_team_for_game
                        db.session.add(game_team)

                        # Create GamePlayers
                        for api_player_stats in api_team_in_game.players:
                            if api_player_stats.id is None:
                                continue

                            # Creates player_data for this specific player
                            player_data_for_creation = {
                                'id': api_player_stats.id,
                                'summonerName': api_player_stats.name,
                                'role': api_player_stats.role,
                                'image': None
                            }
                            # Attempt to retrieve an existing canonical_player
                            # Or create a new canonical_player
                            canonical_player_for_stats = get_or_create_canonical_player(
                                player_data_for_creation,
                                event.league,
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
                                        role=api_player_stats.role,
                                        image=canonical_player_for_stats.image,
                                    )
                                    match_player_for_stats.match_team = target_match_team_for_sub
                                    match_player_for_stats.canonical_player = canonical_player_for_stats
                                    db.session.add(match_player_for_stats)
                                    current_match_players_map[
                                        str(canonical_player_for_stats.external_id)] = match_player_for_stats
                                    app.logger.info(
                                        f"Created MatchPlayer for substitute {canonical_player_for_stats.name} in MatchTeam {target_match_team_for_sub.name}")
                                else:
                                    app.logger.error(
                                        f"Could not find MatchTeam for substitute player {canonical_player_for_stats.name} (associated with CTeam {canonical_team_for_game.name}) in Match for Event PK {event.id}. Skipping GPP.")
                                    continue
                            db.session.flush()
                            # Add a player's stats for a game and pair it to the MatchPlayer and CanonicalPlayer
                            gpp = GamePlayerPerformance(
                                name=canonical_player_for_stats.name,
                                role=api_player_stats.role,
                                champion=api_player_stats.champion,
                                gold=api_player_stats.gold,
                                level=api_player_stats.level,
                                kills=api_player_stats.kills,
                                deaths=api_player_stats.deaths,
                                assists=api_player_stats.assists,
                                creeps=api_player_stats.creeps,
                                canonical_player_id=canonical_player_for_stats.id,
                                match_player_id=match_player_for_stats.id
                            )
                            match_player = match_player_for_stats if match_player_for_stats else None
                            if hasattr(game_team, 'gamePlayers'): game_team.gamePlayers.append(gpp)
                            if hasattr(canonical_player_for_stats,
                                       'game_performances'): canonical_player_for_stats.game_performances.append(gpp)
                            if match_player_for_stats and hasattr(match_player_for_stats, 'game_stats'):
                                match_player_for_stats.game_stats.append(gpp)
                            db.session.add(gpp)
            db.session.commit()
        app.logger.info("Finished processing all new completed events")

# Loops through all unstarted games, looking to update either their TBD teams
# or check for when the game starts
def update_unstarted_events():
    with app.app_context():
        current_time = datetime.now(timezone.utc)
        app.logger.info("SCHEDULER: Running job to update unstarted events. Time: " + str(current_time))
        tbd_events = Event.query.filter(or_(Event.team_one == "TBD", Event.team_two == "TBD")).all()
        for event in tbd_events:
            update_TBD_event(event.id)
            db.session.commit()
        active_events = Event.query.filter(or_(Event.state == 'unstarted', Event.state == 'inProgress')).all()
        for event in active_events:
            start_time = datetime.strptime(event.start_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            # If the event will start in the next 5 minutes
            if (current_time - start_time) > timedelta(minutes=5):
                # Check if a job already exists
                job_id = f"track_unstarted_event_{event.match_id}"
                if not scheduler.get_job(job_id):
                    app.logger.info(
                        f"SCHEDULER: Found an unstarted event, {event.match_id}, scheduled a job for {str(start_time)}")
                    scheduler.add_job(
                        id=job_id,
                        func=track_unstarted_event,
                        trigger='date',
                        run_date=start_time,
                        args=[event.id],
                        misfire_grace_time=None
                    )
                    time.sleep(5)
        app.logger.info("SCHEDULER: Finished updating unstarted events")

# Kicks off tracking a game that started
def track_unstarted_event(event_id):
    with app.app_context():
        event = Event.query.filter_by(id=event_id).first()
        app.logger.info(f"Match {event.match_id} is starting, updating to inProgress")
        event.state = 'inProgress'
        db.session.commit()
        job_id = f"update_in_progress_match_{event.match_id}"
        if not scheduler.get_job(job_id):
            scheduler.add_job(
                id=job_id,
                func=update_in_progress_match,
                trigger='interval',
                seconds=20,  # Run every 20 seconds
                args=[event.id],
                misfire_grace_time = None
            )

# Helper function to retrieve a Game object from a game_id
def get_or_create_game(cur_match, game_id):
    cur_game = Game.query.filter_by(game_id=game_id, match_id=cur_match.id).first()
    if not cur_game:
        cur_game = Game(
            game_id=game_id
        )
        cur_game.match = cur_match
        db.session.add(cur_game)
    return cur_game

# Helper function to retrieve a GameTeam from a team_id
def get_or_create_game_team(cur_game, team_id):
    cur_team = GameTeam.query.filter_by(team_id=team_id, game_id=cur_game.id).first()
    if not cur_team:
        # Find the canonical team
        canonical_team_for_game = CanonicalTeam.query.filter_by(
            external_id=team_id).first()
        cur_team = GameTeam(
            team_id=team_id,
            team_name=canonical_team_for_game.name,
        )
        cur_team.game = cur_game
        cur_team.canonical_team = canonical_team_for_game
        db.session.add(cur_team)
    return cur_team

# Helper function to retrieve a GamePlayerPerformance from a game's player name
def get_or_create_player(cur_team, player):
    player_data_for_creation = {
        'id': player.id,
        'summonerName': player.name,
        'role': player.role,
        'image': None
    }
    canonical_player = get_or_create_canonical_player(
        player_data_for_creation,
        cur_team.canonical_team.league,
        team_to_associate_if_new=cur_team.canonical_team
    )
    cur_player = GamePlayerPerformance.query.filter_by(name=canonical_player.name, team_id=cur_team.id).first()
    if not cur_player:
        # Find the canonical player
        player_data_for_creation = {
            'id': player.id,
            'summonerName': player.name,
            'role': player.role,
            'image': None
        }
        canonical_player = get_or_create_canonical_player(
            player_data_for_creation,
            cur_team.canonical_team.league,
            team_to_associate_if_new=cur_team.canonical_team
        )
        # Find the match_player
        m_player = MatchPlayer.query.filter_by(canonical_player_id=canonical_player.id).first()
        # If no m_player
        if not m_player:
            # Find MatchTeam associated with cur_team
            m_team = MatchTeam.query.filter_by(canonical_team_id=cur_team.canonical_team_id).first()
            # Create a new MatchPlayer
            m_player = MatchPlayer(
                name=canonical_player.name,
                role=player.role,
                image=canonical_player.image,
            )
            m_player.match_team = m_team
            m_player.canonical_player = canonical_player
            db.session.add(m_player)
        cur_player = GamePlayerPerformance(
            name=canonical_player.name,
            role=player.role,
            champion=player.champion,
            gold=player.gold,
            level=player.level,
            kills=player.kills,
            deaths=player.deaths,
            assists=player.assists,
            creeps=player.creeps,
            canonical_player_id=canonical_player.id,
            match_player_id=m_player.id
        )
        cur_team.gamePlayers.append(cur_player)
        canonical_player.game_participations.append(cur_player)
        m_player.game_stats.append(cur_player)
        db.session.add(cur_player)
    else:
        # else, just update the current player's stats
        cur_player.role = player.role
        cur_player.champion = player.champion
        cur_player.gold = player.gold
        cur_player.level = player.level
        cur_player.kills = player.kills
        cur_player.deaths = player.deaths
        cur_player.assists = player.assists
        cur_player.creeps = player.creeps
    return cur_player

# Handles updating a match in progress
def update_in_progress_match(event_id):
    with app.app_context():
        event = Event.query.get(event_id)
        app.logger.info(f"SCHEDULER: Polling for live stats for match {event.match_id}...")
        match_details = lolapi.get_match(event.match_id)

        # update Match assuming MatchTeams and MatchPlayers are already created
        cur_match = event.match

        for game in match_details.games:
            cur_game = get_or_create_game(cur_match, game.id)
            for team in game.teams:
                cur_team = get_or_create_game_team(cur_game, team.team_id)
                for player in team.players:
                    cur_player = get_or_create_player(cur_team, player)

        if match_details.state == 'completed':
            app.logger.info(f"SCHEDULER: Match {event.match_id} has completed. Stopping polling job.")
            event.state = 'completed'
            db.session.commit()
            scheduler.remove_job(id=f"update_in_progress_match_{event.match_id}")
        elif event.state != match_details.state:
            event.state = match_details.state
            db.session.commit()
        else:
            db.session.commit()

def print_jobs():
    for job in scheduler.get_jobs():
        app.logger.info(f"SCHEDULED JOB - ID:{job.id}")