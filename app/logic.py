# app/logic.py
from flask import current_app
from app.models import *
from . import cache

# Caches a user's tracked teams and tracked players
@cache.memoize(timeout=3600)
def get_dashboard_data(user_id):
    current_app.logger.info(f"CACHE MISS: Running optimized query for user {user_id}")
    user = User.query.get(user_id)
    if not user:
        return {}, {}

    tracked_team_ids = [team.id for team in user.tracked_teams]
    tracked_player_ids = [player.id for player in user.tracked_players]

    if not tracked_team_ids and not tracked_player_ids:
        return {}, {}

    all_latest_event_ids = set()

    # Find latest events for tracked teams
    if tracked_team_ids:
        team_subquery = db.session.query(
            Event.id,
            db.func.row_number().over(
                partition_by=MatchTeam.canonical_team_id,
                order_by=desc(Event.start_time_datetime)
            ).label('rn')
        ).join(Match, Event.id == Match.event_id) \
            .join(MatchTeam, Match.id == MatchTeam.match_id) \
            .filter(MatchTeam.canonical_team_id.in_(tracked_team_ids)).subquery()
        team_event_ids = db.session.query(team_subquery.c.id).filter(team_subquery.c.rn == 1).all()
        all_latest_event_ids.update([eid[0] for eid in team_event_ids])

    # Find latest events for tracked players
    if tracked_player_ids:
        player_subquery = db.session.query(
            Event.id,
            db.func.row_number().over(
                partition_by=MatchPlayer.canonical_player_id,
                order_by=desc(Event.start_time_datetime)
            ).label('rn')
        ).join(Match, Event.id == Match.event_id) \
            .join(MatchTeam, Match.id == MatchTeam.match_id) \
            .join(MatchPlayer, MatchTeam.id == MatchPlayer.match_team_id) \
            .filter(MatchPlayer.canonical_player_id.in_(tracked_player_ids)).subquery()
        player_event_ids = db.session.query(player_subquery.c.id).filter(player_subquery.c.rn == 1).all()
        all_latest_event_ids.update([eid[0] for eid in player_event_ids])

    if not all_latest_event_ids:
        return {}, {}

    # Fetch all needed events and their related data in one query
    events = Event.query.filter(Event.id.in_(list(all_latest_event_ids))).options(
        joinedload(Event.match)
        .joinedload(Match.match_teams)
        .joinedload(MatchTeam.canonical_team),
        joinedload(Event.match)
        .joinedload(Match.match_teams)
        .joinedload(MatchTeam.match_players)
        .joinedload(MatchPlayer.canonical_player),
        joinedload(Event.match)
        .joinedload(Match.games)
        .joinedload(Game.gameTeams)
        .joinedload(GameTeam.gamePlayers)
    ).all()

    # Organize the results into maps for easy lookup
    team_event_map = {}
    player_event_map = {}
    for event in events:
        for mt in event.match.match_teams:
            if mt.canonical_team_id in tracked_team_ids:
                team_event_map[mt.canonical_team_id] = event
            for mp in mt.match_players:
                if mp.canonical_player_id in tracked_player_ids:
                    player_event_map[mp.canonical_player_id] = event

    return team_event_map, player_event_map