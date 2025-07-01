from sqlalchemy.orm import relationship, joinedload
from sqlalchemy import desc
from app import db, login_manager
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from sqlalchemy.dialects.postgresql import JSONB

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class UserTrackedItem(db.Model):
    __tablename__ = 'user_tracked_items'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)

    # Can track a team OR a player within an event. One will be null.
    canonical_team_id = db.Column(db.Integer, db.ForeignKey('canonical_teams.id'), nullable=True)
    canonical_player_id = db.Column(db.Integer, db.ForeignKey('canonical_players.id'), nullable=True)

    tracked_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Define relationships to easily access the objects
    user = db.relationship('User', back_populates='tracked_items')
    event = db.relationship('Event')
    team = db.relationship('CanonicalTeam')
    player = db.relationship('CanonicalPlayer')

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True, nullable=False)
    email = db.Column(db.String(120), index=True, unique=True, nullable=False)
    password_hash = db.Column(db.String(256))

    tracked_items = db.relationship('UserTrackedItem', back_populates='user', lazy='dynamic',
                                    cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_tracking(self, event, team=None, player=None):
        """Checks if the user is tracking a specific item in a specific event."""
        query = self.tracked_items.filter_by(event_id=event.id)
        if team:
            query = query.filter_by(canonical_team_id=team.id)
        if player:
            query = query.filter_by(canonical_player_id=player.id)
        return query.count() > 0

    def track(self, event, team=None, player=None):
        """Tracks a team or player for a specific event."""
        if not self.is_tracking(event, team=team, player=player):
            item = UserTrackedItem(
                user_id=self.id,
                event_id=event.id,
                canonical_team_id=team.id if team else None,
                canonical_player_id=player.id if player else None
            )
            db.session.add(item)

    def untrack(self, event, team=None, player=None):
        """Untracks a team or player from a specific event."""
        query = self.tracked_items.filter_by(event_id=event.id)
        if team:
            query = query.filter_by(canonical_team_id=team.id)
        if player:
            query = query.filter_by(canonical_player_id=player.id)
        items_to_delete = query.all()
        for item in items_to_delete:
            db.session.delete(item)

    def untrack_item_by_id(self, item_id):
        """Untracks an item by its specific tracking ID."""
        item = self.tracked_items.filter_by(id=item_id).first()
        if item:
            db.session.delete(item)

    def __repr__(self):
        return f'<User {self.username}>'

class Sport(db.Model):
    __tablename__ = 'sports'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    leagues = db.relationship('League', back_populates='sport')

class League(db.Model):
    __tablename__ = 'leagues'
    id = db.Column(db.Integer, primary_key=True)
    sport_id = db.Column(db.Integer, db.ForeignKey('sports.id'), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    league_id = db.Column(db.String(50), nullable=False)
    image = db.Column(db.String(200))
    last_updated = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)

    canonical_teams = relationship('CanonicalTeam', back_populates='league')
    canonical_players = relationship('CanonicalPlayer', back_populates='league')
    events = relationship('Event', back_populates='league', cascade="all, delete-orphan")
    sport = db.relationship('Sport', back_populates='leagues')

class Event(db.Model):
    __tablename__ = 'events'
    id = db.Column(db.Integer, primary_key=True)
    league_id = db.Column(db.Integer, db.ForeignKey('leagues.id'), nullable=False)
    start_time = db.Column(db.String(50), nullable=False)
    strategy = db.Column(db.Integer)
    state = db.Column(db.String(50), nullable=False)
    match_id = db.Column(db.String(50), nullable=False)
    team_one = db.Column(db.String(50), nullable=False)
    team_two = db.Column(db.String(50), nullable=False)
    last_updated = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)
    start_time_datetime = db.Column(db.DateTime, index=True)
    is_start_scheduled = db.Column(db.Boolean, default=False, nullable=False)

    league = relationship('League', back_populates='events')
    match = relationship('Match', back_populates='event', uselist=False, cascade="all, delete-orphan")

class Match(db.Model):
    __tablename__ = 'matches'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    team_one_id = db.Column(db.String(50), nullable=False)
    team_two_id = db.Column(db.String(50), nullable=False)

    event = relationship('Event', foreign_keys=[event_id], back_populates='match', uselist=False)
    match_teams = relationship('MatchTeam', back_populates='match', cascade="all, delete-orphan")
    games = relationship('Game', back_populates='match', cascade="all, delete-orphan")

class MatchTeam(db.Model):
    __tablename__ = 'match_teams'

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    canonical_team_id = db.Column(db.Integer, db.ForeignKey('canonical_teams.id'))
    name = db.Column(db.String(50), nullable=False)
    image = db.Column(db.String(200))
    # could include side, score_for_match, result_for_match, etc.

    match = relationship('Match', back_populates='match_teams')
    match_players = relationship('MatchPlayer', back_populates='match_team', cascade="all, delete-orphan")
    canonical_team = relationship('CanonicalTeam', back_populates='match_participations')

class MatchPlayer(db.Model):
    __tablename__ = 'match_players'

    id = db.Column(db.Integer, primary_key=True)
    match_team_id = db.Column(db.Integer, db.ForeignKey('match_teams.id'), nullable=False)
    canonical_player_id = db.Column(db.Integer, db.ForeignKey('canonical_players.id'), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    image = db.Column(db.String(200))

    game_stats = relationship('GamePlayerPerformance', back_populates='match_player', cascade="all, delete-orphan")
    canonical_player = relationship('CanonicalPlayer', back_populates='match_participations')
    match_team = relationship('MatchTeam', back_populates='match_players')

class Game(db.Model):
    __tablename__ = 'games'

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    game_id = db.Column(db.String(50), nullable=False)
    # could include game number, duration, status, etc.

    match = relationship('Match', back_populates='games')
    gameTeams = relationship('GameTeam', back_populates='game', cascade="all, delete-orphan")

class GameTeam(db.Model):
    __tablename__ = 'gameteams'

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey('games.id'), nullable=False)
    canonical_team_id = db.Column(db.Integer, db.ForeignKey('canonical_teams.id'), nullable=False)
    team_id = db.Column(db.String(50))
    team_name = db.Column(db.String(50))
    # could include team stats, side, result, etc.

    game = relationship('Game', back_populates='gameTeams')
    gamePlayers = relationship('GamePlayerPerformance', back_populates='gameTeam', cascade="all, delete-orphan")
    canonical_team = relationship('CanonicalTeam', back_populates='game_participations')

class GamePlayerPerformance(db.Model):
    __tablename__ = 'gameplayers'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('gameteams.id'), nullable=False)
    canonical_player_id = db.Column(db.Integer, db.ForeignKey('canonical_players.id'), nullable=False)
    match_player_id = db.Column(db.Integer, db.ForeignKey('match_players.id'), nullable=False)

    stats = db.Column(JSONB, nullable=False)

    match_player = relationship('MatchPlayer', back_populates='game_stats')
    canonical_player = relationship('CanonicalPlayer', back_populates='game_participations')
    gameTeam = relationship('GameTeam', back_populates='gamePlayers')

class CanonicalTeam(db.Model):
    __tablename__ = 'canonical_teams'

    id = db.Column(db.Integer, primary_key=True)
    league_id = db.Column(db.Integer, db.ForeignKey('leagues.id'), nullable=False)
    external_id = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    image = db.Column(db.String(200))
    # could include other info about the team here

    league = relationship('League', back_populates='canonical_teams')
    canonical_players = relationship('CanonicalPlayer', back_populates='canonical_team')
    match_participations = relationship('MatchTeam', back_populates='canonical_team', cascade="all, delete-orphan")
    game_participations = relationship('GameTeam', back_populates='canonical_team', cascade="all, delete-orphan")

class CanonicalPlayer(db.Model):
    __tablename__ = 'canonical_players'

    id = db.Column(db.Integer, primary_key=True)
    league_id = db.Column(db.Integer, db.ForeignKey('leagues.id'), nullable=False)
    canonical_team_id = db.Column(db.Integer, db.ForeignKey('canonical_teams.id'), nullable=False)
    external_id = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    image = db.Column(db.String(200))
    role = db.Column(db.String(50), nullable=False)

    league = relationship('League', back_populates='canonical_players')
    canonical_team = relationship('CanonicalTeam', back_populates='canonical_players')
    match_participations = relationship('MatchPlayer', back_populates='canonical_player', cascade="all, delete-orphan")
    game_participations = relationship('GamePlayerPerformance', back_populates='canonical_player', cascade="all, delete-orphan")