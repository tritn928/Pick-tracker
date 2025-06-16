from flask import current_app
from app import scheduler
from app import db, cache
from app.models import *
from app.routes import _get_latest_events_for_entities
from lolesports_api.rest_adapter import RestAdapter
import time
from datetime import datetime, timedelta, timezone
from sqlalchemy import or_

from seed import get_or_create_canonical_player, get_or_create_canonical_team

lolapi = RestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')

# Updates all leagues with new Events
# Kicks off additional jobs to populate the events
def update_leagues():
    print("getting here...")
    with current_app.app_context():
        current_app.logger.info("SCHEDULER: Running job to update leagues. Time: " + str(datetime.now(timezone.utc)))
        all_leagues = League.query.all()
        for league in all_leagues:
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
                        league_id=league.id
                    )
                    events_to_add.append(new_event)
            if events_to_add:
                db.session.add_all(events_to_add)
                db.session.commit()
            time.sleep(.5)
        current_app.logger.info("SCHEDULER: Finished updating all leagues. Time: " + str(datetime.now(timezone.utc)))
        job_id = f"update_completed_events"
        if not scheduler.get_job(job_id):
            current_app.logger.info(
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
            current_app.logger.info(
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
    with current_app.app_context():
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
            current_app.logger.info(f"SCHEDULER: Updated Unstarted Event {event.id} in league {event.league.name}")
        current_app.logger.info("SCHEDULER: Finished populating unstarted events")

# Updates unstarted events with TBD teams
def update_TBD_event(event_id):
    with current_app.app_context():
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
        current_app.logger.info(f"Finished updating TBD event with ID {event.id} in league {event.league.name}")

# Populates newly added completed events
def populate_completed_events():
    with current_app.app_context():
        events_to_check = Event.query.filter(
            Event.state == 'completed',
            or_(
                Event.match == None,
                Event.match.has(~Match.games.any())
            )
        ).all()
        for event in events_to_check:
            current_app.logger.info(f"Processing Event (PK: {event.id}, API MatchID: {event.match_id}) for match creation.")
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
                                    current_app.logger.info(
                                        f"Created MatchPlayer for substitute {canonical_player_for_stats.name} in MatchTeam {target_match_team_for_sub.name}")
                                else:
                                    current_app.logger.error(
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
        current_app.logger.info("Finished processing all new completed events")

# Updates TBD teams and then schedules live tracking for events that are about to start.
def process_unstarted_events():
    with current_app.app_context():
        now = datetime.now(timezone.utc)
        current_app.logger.info(f"SCHEDULER: Running job to process unstarted events at {now.isoformat()}")

        unstarted_events = Event.query.filter_by(state='unstarted').all()

        # Update events with TBD teams
        tbd_events = [e for e in unstarted_events if e.team_one == 'TBD' or e.team_two == 'TBD']
        if tbd_events:
            current_app.logger.info(f"Found {len(tbd_events)} unstarted events with TBD teams to update.")
            for event in tbd_events:
                try:
                    update_TBD_event(event.id)
                except Exception as e:
                    current_app.logger.error(f"Error updating TBD for Event {event.id}: {e}")
                    db.session.rollback()
            db.session.commit()

        events_to_check = [e for e in unstarted_events if e.team_one != 'TBD' and e.team_two != 'TBD']

        for event in events_to_check:
            if not event.start_time_datetime:
                try:
                    event.start_time_datetime = datetime.strptime(event.start_time, "%Y-%m-%dT%H:%M:%SZ").replace(
                        tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    current_app.logger.warning(f"Could not parse start_time for Event {event.id}. Skipping start check.")
                    continue

            start_time = event.start_time_datetime.replace(tzinfo=timezone.utc)
            if (now - start_time) > timedelta(minutes=5):
                job_id = f"start_tracking_match_{event.match_id}"
                if not scheduler.get_job(job_id):
                    current_app.logger.info(
                        f"SCHEDULER: Event {event.match_id} is starting soon. Scheduling job to run at {start_time.isoformat()}")
                    scheduler.add_job(
                        id=job_id,
                        func='app.tasks:track_unstarted_event',
                        trigger='date',
                        run_date=start_time,
                        args=[event.id],
                        misfire_grace_time=None
                    )

        current_app.logger.info("SCHEDULER: Finished processing unstarted events.")

# updates the event state and schedules the recurring "in-progress" job
def track_unstarted_event(event_id):
    with current_app.app_context():
        event = Event.query.get(event_id)
        if not event:
            current_app.logger.error(f"SCHEDULER: Can't track event, Event ID {event_id} not found.")
            return

        current_app.logger.info(f"Match {event.match_id} is starting. Updating state to inProgress.")
        event.state = 'inProgress'
        db.session.commit()

        job_id = f"update_in_progress_match_{event.match_id}"
        if not scheduler.get_job(job_id):
            scheduler.add_job(
                id=job_id,
                func='app.tasks:update_in_progress_match',
                trigger='interval',
                seconds=20,
                args=[event.id],
                misfire_grace_time=None
            )

        job_id = f"update_invalidate_caches_for_live_games"
        if not scheduler.get_job(job_id):
            scheduler.add_job(
                id=job_id,
                func=invalidate_caches_for_live_games,
                trigger='interval',
                minutes=1,
                replace_existing=True,
                misfire_grace_time = None,
                next_run_time=datetime.now()
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
    with current_app.app_context():
        event = Event.query.get(event_id)
        current_app.logger.info(f"SCHEDULER: Polling for live stats for match {event.match_id}...")
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
            current_app.logger.info(f"SCHEDULER: Match {event.match_id} has completed. Stopping polling job.")
            invalidate_caches_for_live_games()
            event.state = 'completed'
            db.session.commit()
            scheduler.remove_job(id=f"update_in_progress_match_{event.match_id}")
        elif event.state != match_details.state:
            event.state = match_details.state
            db.session.commit()
        else:
            db.session.commit()

def print_jobs():
    print("IN PRINT_JOBS")
    with current_app.app_context():
        for job in scheduler.get_jobs():
            print("JOB")
            current_app.logger.info(f"SCHEDULED JOB - ID:{job.id}")

# Finds and deletes MatchPlayer records that have no associated game statistics
# Only cleans up completed events
def cleanup_unused_match_players():
    with current_app.app_context():
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
        current_app.logger.info(f"Found {len(all_players_in_completed_matches_ids)} total MatchPlayer IDs in completed events.")

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

# Finds all users tracking any live game and clear their dashboard cache
def invalidate_caches_for_live_games():
    with current_app.app_context():
        current_app.logger.info("SCHEDULER: Running job to invalidate caches for live games.")

        # Query all events in progress
        live_event_ids_query = db.session.query(Event.id).filter(Event.state == 'inProgress')
        live_event_ids = {row.id for row in live_event_ids_query}

        if not live_event_ids:
            current_app.logger.info("SCHEDULER: No live games found. No caches to invalidate.")
            return

        # Query all users that are tracking the team
        users_tracking_live_teams_query = db.session.query(user_tracked_teams.c.user_id).join(
            MatchTeam, user_tracked_teams.c.canonical_team_id == MatchTeam.canonical_team_id
        ).join(
            Match, MatchTeam.match_id == Match.id
        ).filter(Match.event_id.in_(live_event_ids)).distinct()

        user_ids_to_invalidate = {row.user_id for row in users_tracking_live_teams_query}

        # Query all users that are tracking the player
        users_tracking_live_players_query = db.session.query(user_tracked_players.c.user_id).join(
            MatchPlayer, user_tracked_players.c.canonical_player_id == MatchPlayer.canonical_player_id
        ).join(
            MatchTeam, MatchPlayer.match_team_id == MatchTeam.id
        ).join(
            Match, MatchTeam.match_id == Match.id
        ).filter(Match.event_id.in_(live_event_ids)).distinct()

        user_ids_to_invalidate.update(row.user_id for row in users_tracking_live_players_query)

        if not user_ids_to_invalidate:
            current_app.logger.info("SCHEDULER: No users are tracking the current live games.")
            # Stop running script
            job_id = f"update_invalidate_caches_for_live_games"
            scheduler.remove_job(id=job_id)
            return

        current_app.logger.info(f"SCHEDULER: Found {len(user_ids_to_invalidate)} users whose cache needs to be invalidated.")
        for user_id in user_ids_to_invalidate:
            cache.delete_memoized(_get_latest_events_for_entities, user_id)
            current_app.logger.debug(f"SCHEDULER: Deleted cache for user {user_id}")

def check_in_progress():
    with current_app.app_context():
        current_app.logger.info("SCHEDULER: Start checking all in_progress events")
        events_to_check = Event.query.filter(Event.state == 'inProgress').all()
        for event in events_to_check:
            job_id = f"update_in_progress_match_{event.match_id}"
            if not scheduler.get_job(job_id):
                scheduler.add_job(
                    id=job_id,
                    func='app.tasks:update_in_progress_match',
                    trigger='interval',
                    seconds=20,
                    args=[event.id],
                    misfire_grace_time=None
                )
            time.sleep(2)
        current_app.logger.info("SCHEDULER: Finished checking all in_progress events")