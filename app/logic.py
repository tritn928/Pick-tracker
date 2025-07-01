# app/logic.py
from flask import current_app
from app.models import *
from . import cache
from sqlalchemy.orm import joinedload, subqueryload
from sqlalchemy import desc


def get_dashboard_data(user_id):
    # 1. Get the list of all tracked items from the database. This is a fast query.
    tracked_items = UserTrackedItem.query.filter_by(user_id=user_id).options(
        joinedload(UserTrackedItem.event).joinedload(Event.league).joinedload(League.sport),
        joinedload(UserTrackedItem.team),
        joinedload(UserTrackedItem.player)
    ).order_by(desc(UserTrackedItem.tracked_at)).all()

    # 2. Loop through each item and attach the correct display data.
    for item in tracked_items:
        item.display_data = None  # Initialize the display data
        event = item.event
        if not event:
            continue

        # --- HYBRID LOGIC ---
        if event.state == 'inProgress':
            # For live games, get data from the live cache
            redis_key = f"match_state:{event.match_id}"
            live_match_object = cache.get(redis_key)
            if live_match_object:
                item.display_data = live_match_object.to_dict()

        elif event.state == 'completed':
            # For completed games, use the cache-aside pattern
            redis_key = f"completed_match:{event.match_id}"
            cached_data = cache.get(redis_key)

            if cached_data:
                # CACHE HIT: Use the data from the cache
                item.display_data = cached_data
            else:
                # CACHE MISS: Query the DB, convert, and store in cache
                current_app.logger.info(f"CACHE MISS (Completed): Fetching match {event.match_id} from DB.")
                db_match = Match.query.filter_by(event_id=event.id).options(
                    # Add all necessary joined loads for a full data fetch
                    subqueryload(Match.games).subqueryload(Game.gameTeams).subqueryload(GameTeam.gamePlayers)
                ).first()

                # Convert the DB object to the consistent dictionary format
                if event.league.sport.name == 'League of Legends':
                    converted_data = lol_convert_db_match_to_dict(db_match)
                elif event.league.sport.name == 'Baseball':
                    converted_data = mlb_convert_db_match_to_dict(db_match)
                else:
                    converted_data = None

                if converted_data:
                    # Store the result in the cache for future requests (e.g., for 24 hours)
                    cache.set(redis_key, converted_data, timeout=24 * 60 * 60)
                    item.display_data = converted_data

    return tracked_items


def lol_convert_db_match_to_dict(db_match):
    """
    Converts a SQLAlchemy Match object for a LoL game into a dictionary.
    This version uses explicit loops for clarity and correctness.
    """
    if not db_match:
        return None

    games_list = []
    for game in db_match.games:
        participants_dict = {}
        for team in game.gameTeams:
            for player_performance in team.gamePlayers:
                stats_data = player_performance.stats
                p_id = stats_data.get('p_id')
                if p_id:
                    participants_dict[p_id] = stats_data

        game_dict = {
            "game_id": game.game_id,
            "state": None,
            "number": None,
            "blue_team": {"name": game.gameTeams[0].team_name if game.gameTeams else "TBD"},
            "red_team": {"name": game.gameTeams[1].team_name if len(game.gameTeams) > 1 else "TBD"},
            "participants": participants_dict
        }
        games_list.append(game_dict)

    return {
        "match_id": db_match.event.match_id,
        "state": db_match.event.state,
        "games": games_list
    }


def mlb_convert_db_match_to_dict(db_match):
    """
    Converts a SQLAlchemy Match object for an MLB game into a dictionary.
    """
    if not db_match or not db_match.games:
        return None

    # MLB has only one 'game' entry per match
    game = db_match.games[0]

    # Assuming the first team in gameTeams is away, second is home. Adjust if needed.
    away_team_data = game.gameTeams[1] if len(game.gameTeams) > 1 else None
    home_team_data = game.gameTeams[0] if len(game.gameTeams) > 0 else None

    return {
        "id": db_match.event.match_id,
        "state": db_match.event.state,
        "home_team": {
            "id": home_team_data.canonical_team.id if home_team_data else None,
            "name": home_team_data.team_name if home_team_data else "TBD",
            "players": {
                p.match_player.canonical_player.id: p.stats
                for p in home_team_data.gamePlayers if p.match_player and p.match_player.canonical_player
            } if home_team_data else {}
        },
        "away_team": {
            "id": away_team_data.canonical_team.id if away_team_data else None,
            "name": away_team_data.team_name if away_team_data else "TBD",
            "players": {
                p.match_player.canonical_player.id: p.stats
                for p in away_team_data.gamePlayers if p.match_player and p.match_player.canonical_player
            } if away_team_data else {}
        }
    }


# This function now always returns a dictionary
def get_match_display_data(event_id: int):
    """
    Gets all data needed for the match page, always returning a consistent dictionary.
    """
    event = db.get_or_404(Event, event_id)
    if not event or not event.match_id:
        return None, None

    # 1. Check the cache for a live version
    redis_key = f"match_state:{event.match_id}"
    live_match_object = cache.get(redis_key)

    if live_match_object:
        # If live, convert the API wrapper object to a dict
        return event, live_match_object.to_dict()

    # 2. If not live, fetch from the database
    db_match = Match.query.filter_by(event_id=event.id).options(
        joinedload(Match.event),
        joinedload(Match.games).joinedload(Game.gameTeams).joinedload(GameTeam.gamePlayers)
    ).first()

    # Convert the database object to the same dictionary structure
    if event.league.sport.name == 'League of Legends':
        completed_match_dict = lol_convert_db_match_to_dict(db_match)
    else:
        completed_match_dict = mlb_convert_db_match_to_dict(db_match)

    return event, completed_match_dict