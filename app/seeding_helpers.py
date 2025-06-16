from sqlalchemy.exc import IntegrityError
from app import db
from app.models import CanonicalPlayer, CanonicalTeam
from flask import current_app


def get_or_create_canonical_player(player_data, related_league, team_to_associate_if_new=None):
    """
    Safely gets or creates a CanonicalPlayer, handling potential race conditions.
    NOTE: This function adds a new object to the session but does NOT commit it.
    The calling function is responsible for the final db.session.commit().
    """
    player_external_id = player_data.get('id')
    if not player_external_id:
        return None

    # First, try to get the player
    canonical_player = CanonicalPlayer.query.filter_by(external_id=player_external_id).first()
    if canonical_player:
        return canonical_player

    # If it doesn't exist, try to create it
    try:
        new_player = CanonicalPlayer(
            external_id=player_data['id'],
            name=player_data.get('summonerName'),
            image=player_data.get('image'),
            role=player_data.get('role'),
            league=related_league,
            canonical_team=team_to_associate_if_new
        )
        db.session.add(new_player)
        # Flush to assign a primary key, which might be needed by subsequent operations
        # within the same transaction, without committing.
        db.session.flush()
        return new_player
    except IntegrityError:
        # Another worker created this player between our check and our add.
        # This is expected in a parallel environment. We just roll back the session
        # to a clean state and fetch the object that the other worker created.
        db.session.rollback()
        return CanonicalPlayer.query.filter_by(external_id=player_external_id).first()


def get_or_create_canonical_team(team_data, related_league):
    """
    Safely gets or creates a CanonicalTeam and its associated players.
    NOTE: This function adds new objects to the session but does NOT commit them.
    The calling function is responsible for the final db.session.commit().
    """
    team_external_id = team_data.get('id')
    if not team_external_id:
        return None

    canonical_team = CanonicalTeam.query.filter_by(external_id=team_external_id).first()
    if canonical_team:
        return canonical_team

    try:
        new_team = CanonicalTeam(
            external_id=team_data['id'],
            name=team_data.get('name'),
            image=team_data.get('image'),
            league=related_league
        )
        db.session.add(new_team)
        # Flush to get the new_team ID before associating players
        db.session.flush()

        # Now that the team is created, associate players
        for player_data in team_data.get('players', []):
            get_or_create_canonical_player(player_data, related_league, team_to_associate_if_new=new_team)

        return new_team
    except IntegrityError:
        db.session.rollback()
        return CanonicalTeam.query.filter_by(external_id=team_external_id).first()