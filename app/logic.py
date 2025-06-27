# app/logic.py
from flask import current_app
from app.models import *
from . import cache
from sqlalchemy.orm import joinedload
from sqlalchemy import desc


@cache.memoize(timeout=3600)  # Cache the results for 1 hour
def get_dashboard_data(user_id):
    """
    Performs one single, optimized query to get all of a user's tracked items
    and all the nested data needed for the dashboard, preventing N+1 performance problems.
    """
    current_app.logger.info(f"CACHE MISS: Running dashboard query for user {user_id}")

    # This single query gets all tracked items and eagerly loads all related data
    tracked_items = UserTrackedItem.query.filter_by(user_id=user_id).options(
        joinedload(UserTrackedItem.event).joinedload(Event.match).joinedload(Match.games).joinedload(
            Game.gameTeams).joinedload(GameTeam.gamePlayers).joinedload(GamePlayerPerformance.match_player).joinedload(
            MatchPlayer.canonical_player),
        joinedload(UserTrackedItem.team),
        joinedload(UserTrackedItem.player)
    ).order_by(desc(UserTrackedItem.tracked_at)).all()

    return tracked_items