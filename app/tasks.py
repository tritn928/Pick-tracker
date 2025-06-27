from psycopg import OperationalError
from sqlalchemy import or_
from app.seeding_helpers import get_or_create_canonical_team, get_or_create_canonical_player
from app import cache
from .celery_app import celery
from lolesports_api.rest_adapter import RestAdapter
from app.models import *
from flask import current_app
import time
from celery import chain, group

from .logic import get_dashboard_data

lolapi = RestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')

@celery.task
def invalidate_dashboard_cache(user_id):
    """Deletes the cached dashboard data for a single user."""
    try:
        # Use cache.delete_memoized(), passing it the function object
        # and the arguments that were used to create the cache key.
        cache.delete_memoized(get_dashboard_data, user_id)
        current_app.logger.info(f"Invalidated dashboard cache for user {user_id}.")
    except Exception as e:
        current_app.logger.error(f"Failed to invalidate cache for user {user_id}: {e}")

# Updates all leagues with new Events
# Kicks off additional jobs to populate the events
@celery.task
def update_leagues():
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
                    league_id=league.id,
                    start_time_datetime= datetime.strptime(event.start_time, "%Y-%m-%dT%H:%M:%SZ").replace(
                        tzinfo=timezone.utc),
                    is_start_scheduled = False
                )
                events_to_add.append(new_event)
        if events_to_add:
            db.session.add_all(events_to_add)
            db.session.commit()
        time.sleep(.2)
    current_app.logger.info("SCHEDULER: Finished task update_leagues. Time: " + str(datetime.now(timezone.utc)))

@celery.task(bind=True)
# Populates newly added completed events
def populate_unstarted_events(self):
    with current_app.app_context():
        try:
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
        except OperationalError as exc:
            raise self.retry(exc=exc, countdown=60, max_retries=3)
        except Exception as exc:
            current_app.logger.error("NONOperationalError Exception")
            raise

@celery.task()
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

@celery.task(bind=True)
# Populates newly added completed events
def populate_completed_events(self):
    with current_app.app_context():
        try:
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
                                player_stats_dict = {
                                    'name': canonical_player_for_stats.name,
                                    'role': api_player_stats.role,
                                    'champion': api_player_stats.champion,
                                    'gold': api_player_stats.gold,
                                    'level': api_player_stats.level,
                                    'kills': api_player_stats.kills,
                                    'deaths': api_player_stats.deaths,
                                    'assists': api_player_stats.assists,
                                    'creeps': api_player_stats.creeps
                                }
                                gpp = GamePlayerPerformance(stats=player_stats_dict,
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
    cur_player = GamePlayerPerformance.query.filter(
        GamePlayerPerformance.stats['name'].astext == canonical_player.name,
        GamePlayerPerformance.team_id == cur_team.id
    ).first()
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
        player_stats_dict = {
            'name': canonical_player.name,
            'role': player.role,
            'champion': player.champion,
            'gold': player.gold,
            'level': player.level,
            'kills': player.kills,
            'deaths': player.deaths,
            'assists': player.assists,
            'creeps': player.creeps
        }
        cur_player = GamePlayerPerformance(stats=player_stats_dict,
                                    canonical_player_id=canonical_player.id,
                                    match_player_id=m_player.id
                                    )
        cur_team.gamePlayers.append(cur_player)
        canonical_player.game_participations.append(cur_player)
        m_player.game_stats.append(cur_player)
        db.session.add(cur_player)
    else:
        # else, just update the current player's stats
        cur_player.stats['role'] = player.role
        cur_player.stats['champion'] = player.champion
        cur_player.stats['gold'] = player.gold
        cur_player.stats['level'] = player.level
        cur_player.stats['kills'] = player.kills
        cur_player.stats['deaths'] = player.deaths
        cur_player.stats['assists'] = player.assists
        cur_player.stats['creeps'] = player.creeps
    return cur_player

@celery.task(bind=True)
# Handles updating a match in progress
def update_in_progress_match(self, event_id):
    with current_app.app_context():
        try:
            event = Event.query.get(event_id)
            lock_key = f"polling_lock_match_{event.match_id}"
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

            # Now, check the state to decide what to do next
            invalidate_caches_for_live_games()  # Your function to clear user caches
            if match_details.state == 'completed':
                current_app.logger.info(f"Match {event.match_id} has completed. Stopping polling.")

                # Perform final actions
                event.state = 'completed'
                db.session.commit()

                # *** THIS REPLACES `scheduler.remove_job()` ***
                # Release the lock so the main checker knows it can start a new poll
                # for this match in the future if it ever goes live again.
                cache.delete(lock_key)

            else:
                # The match is not complete, so re-queue this same task to run again.
                current_app.logger.info(f"Match {event.match_id} is still in progress. Re-queueing polling task.")

                # *** THIS REPLACES THE 'interval' TRIGGER ***
                # Use apply_async with a countdown to run this task again in 20 seconds.
                update_in_progress_match.apply_async(args=[event_id], countdown=20)
        except OperationalError as exc:
            raise self.retry(exc=exc, countdown=60, max_retries=3)
        except Exception as exc:
            current_app.logger.error("NONOperationalError Exception")
            raise

@celery.task
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

@celery.task(bind=True)
# Finds all users tracking any live game and clear their dashboard cache
def invalidate_caches_for_live_games(self):
    """
    Finds all users tracking any live game and clears their dashboard cache.
    This version is updated to use the UserTrackedItem model.
    """
    with current_app.app_context():
        current_app.logger.info("SCHEDULER: Running job to invalidate caches for live games.")

        try:
            # Step 1: Find all 'inProgress' event IDs. This is a fast query.
            live_event_ids_query = db.session.query(Event.id).filter(Event.state == 'inProgress')
            live_event_ids = {row.id for row in live_event_ids_query}

            if not live_event_ids:
                current_app.logger.info("SCHEDULER: No live games found. No caches to invalidate.")
                return

            # Step 2: Find all unique user IDs who are tracking one of the live events.
            # This is much simpler with the new model.
            user_ids_to_invalidate_query = db.session.query(UserTrackedItem.user_id).filter(
                UserTrackedItem.event_id.in_(live_event_ids)
            ).distinct()

            user_ids_to_invalidate = {row.user_id for row in user_ids_to_invalidate_query}

            if not user_ids_to_invalidate:
                current_app.logger.info("SCHEDULER: No users are tracking the current live games.")
                return

            current_app.logger.info(
                f"SCHEDULER: Found {len(user_ids_to_invalidate)} users whose cache needs to be invalidated.")
            for user_id in user_ids_to_invalidate:
                cache.delete_memoized(get_dashboard_data, user_id=user_id)
                current_app.logger.debug(f"SCHEDULER: Deleted dashboard cache for user {user_id}")

        except Exception as e:
            # It's good practice to log any errors that occur in a background task
            current_app.logger.error(f"An error occurred during cache invalidation: {e}", exc_info=True)


@celery.task(bind=True)
def check_in_progress(self):
    """
    Finds all 'inProgress' events and starts a polling task chain for each one,
    but only if a polling chain isn't already active for that match.
    """
    try:
        current_app.logger.info("Checking for all in_progress events...")
        events_to_check = Event.query.filter(Event.state == 'inProgress').all()

        for event in events_to_check:
            # Simply call the helper. The lock inside will prevent duplicate chains.
            start_match_polling_chain.delay(event.id)

        current_app.logger.info("Finished checking for all in_progress events.")
    except OperationalError as exc:
        raise self.retry(exc=exc, countdown=60, max_retries=3)

    except Exception as exc:
        current_app.logger.error("NONOperationalError Exception")
        raise

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
        cache.set(lock_key, "locked", timeout=300) # 5-minute safety timeout

        # 3. Kick off the first run of the actual polling task
        update_in_progress_match.delay(event.id)
    except OperationalError as exc:
        raise self.retry(exc=exc, countdown=60, max_retries=3)

    except Exception as exc:
        current_app.logger.error("NONOperationalError Exception")
        raise

@celery.task(bind=True)
# Updates TBD teams and then schedules live tracking for events that are about to start.
def process_unstarted_events(self):
    """
    Runs periodically (e.g., every hour) to update TBD events and schedule
    start-time jobs for newly resolved or discovered events.
    """
    with current_app.app_context():
        try:
            now = datetime.now(timezone.utc)
            current_app.logger.info(f"SCHEDULER: Running job to process unstarted events at {now.isoformat()}")

            # --- Step 1: Update TBD Events (Same as before) ---
            tbd_events = Event.query.filter(
                Event.state == 'unstarted',
                db.or_(Event.team_one == 'TBD', Event.team_two == 'TBD')
            ).all()

            if tbd_events:
                current_app.logger.info(f"Found {len(tbd_events)} TBD events to update.")
                for event in tbd_events:
                    try:
                        update_TBD_event(event.id)
                    except Exception as e:
                        current_app.logger.error(f"Error updating TBD for Event {event.id}: {e}")
                        db.session.rollback()
                db.session.commit()

            # --- Step 2: Schedule Start Jobs for New/Resolved Events ---
            # Find events that have resolved teams but haven't had their start job scheduled yet.
            events_to_schedule = Event.query.filter(
                Event.state == 'unstarted',
                Event.is_start_scheduled == False,
                Event.team_one != 'TBD',
                Event.team_two != 'TBD'
            ).all()

            if not events_to_schedule:
                current_app.logger.info("No new events to schedule.")
                return

            current_app.logger.info(f"Found {len(events_to_schedule)} new/resolved events to schedule.")
            for event in events_to_schedule:
                if not event.start_time_datetime:
                    # Skip if there's no valid start time yet
                    continue

                # The 'if event.start_time_datetime > now:' check has been removed.
                # Celery will now schedule the task to run immediately if the ETA is in the past.
                current_app.logger.info(
                    f"Scheduling start task for Event {event.id} at {event.start_time_datetime.isoformat()}")

                # Use apply_async with an ETA to schedule the task for the exact start time
                start_match_polling_chain.apply_async(
                    args=[event.id],
                    eta=event.start_time_datetime
                )

                # Mark this event as scheduled to prevent re-scheduling
                event.is_start_scheduled = True

            # Commit the changes (setting is_start_scheduled to True)
            db.session.commit()
            current_app.logger.info("Finished scheduling start jobs.")

        except OperationalError as exc:
            raise self.retry(exc=exc, countdown=60, max_retries=3)
        except Exception as exc:
            current_app.logger.error(f"An unexpected error occurred in process_unstarted_events: {exc}", exc_info=True)
            raise

# --- Stage 1 Task ---
@celery.task(name='tasks.seed_leagues')
def seed_leagues_task():
    """Seeds all leagues from the API."""
    current_app.logger.info("Starting task: seed_leagues_task")
    ignore = ['LCL', "TFT Esports ", 'LCS', "King's Duel", 'Worlds Qualifying Series', 'LCO', 'LLA', 'CBLOL', 'Arabian League']
    leagues_list = lolapi.get_leagues()
    to_add = [
        League(name=league['name'], league_id=league['id'], image=league['image'])
        for league in leagues_list if league['name'] not in ignore
    ]
    if to_add:
        # Use bulk_save_objects for efficient batch inserting
        db.session.bulk_save_objects(to_add)
        db.session.commit()
    current_app.logger.info(f"Finished seeding {len(to_add)} leagues.")


# --- Stage 2 Task ---
@celery.task(name='tasks.seed_events_for_league')
def seed_events_for_league_task(league_id):
    """Seeds all events for a single league."""
    league = League.query.get(league_id)
    if not league:
        return

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
            is_start_scheduled = False
        )
        to_add.append(new_event)

    if to_add:
        db.session.bulk_save_objects(to_add)
        db.session.commit()
    time.sleep(0.4)  # Keep API rate limiting if necessary


# --- Stage 3 Task ---
@celery.task(name='tasks.seed_match_for_event', bind=True)
def seed_match_for_event_task(self, event_id):
    """Seeds the detailed match data for a single event."""
    event = Event.query.get(event_id)
    if not event:
        current_app.logger.warning(f"Skipping match seed: Event ID {event_id} not found.")
        return
    if event.match:  # Skip if match is already seeded
        current_app.logger.info(f"Skipping match seed: Event {event.match_id} already has a match.")
        return

    current_app.logger.info(f"Starting to seed match for event: {event.match_id} (Event PK: {event.id})")

    try:
        match_details_api = lolapi.get_match(event.match_id)

        # *** THE FIX IS HERE: Associate the new match with the event ***
        new_match = Match(team_one_id=match_details_api.team_ids[0], team_two_id=match_details_api.team_ids[1])
        event.match = new_match  # This line was missing

        current_match_players_map = {}
        # Now this line will work correctly
        api_teams_in_match = lolapi.get_teams([event.match.team_one_id, event.match.team_two_id])

        # Gets the teams involved in the match
        for api_team_data in api_teams_in_match:
            if api_team_data['name'] == 'TBD':
                match_team = MatchTeam(name='TBD', image=None, match=new_match)
                db.session.add(match_team)
                continue

            canonical_team = get_or_create_canonical_team(api_team_data, event.league)
            match_team = MatchTeam(name=canonical_team.name, image=canonical_team.image, match=new_match,
                                   canonical_team=canonical_team)
            db.session.add(match_team)

            # Create MatchPlayers
            for api_player_data in api_team_data.get('players', []):
                canonical_player = get_or_create_canonical_player(api_player_data, event.league, canonical_team)
                if canonical_player:
                    match_player = MatchPlayer(name=canonical_player.name, role=api_player_data['role'],
                                               image=canonical_player.image, match_team=match_team,
                                               canonical_player=canonical_player)
                    db.session.add(match_player)
                    current_match_players_map[canonical_player.external_id] = match_player

        # Adds the existing games
        if not event.match.games:
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

                        player_stats_dict = {
                            'name': canonical_player_for_stats.name,
                            'role': api_player_stats.role,
                            'champion': api_player_stats.champion,
                            'gold': api_player_stats.gold,
                            'level': api_player_stats.level,
                            'kills': api_player_stats.kills,
                            'deaths': api_player_stats.deaths,
                            'assists': api_player_stats.assists,
                            'creeps': api_player_stats.creeps
                        }
                        gpp = GamePlayerPerformance(stats=player_stats_dict,
                                                    canonical_player_id=canonical_player_for_stats.id,
                                                    match_player_id=match_player_for_stats.id
                                                    )
                        match_player = match_player_for_stats if match_player_for_stats else None
                        if hasattr(game_team, 'gamePlayers'): game_team.gamePlayers.append(gpp)
                        if hasattr(canonical_player_for_stats,
                                   'game_performances'): canonical_player_for_stats.game_performances.append(
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
        raise self.retry(exc=e, countdown=60)
