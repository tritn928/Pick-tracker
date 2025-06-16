from sqlalchemy.orm import relationship, joinedload
from sqlalchemy import desc
from app import db, login_manager
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# This table links Users to the CanonicalTeams they are tracking.
user_tracked_teams = db.Table('user_tracked_teams',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('canonical_team_id', db.Integer, db.ForeignKey('canonical_teams.id'), primary_key=True)
)

# This table links Users to the CanonicalPlayers they are tracking.
user_tracked_players = db.Table('user_tracked_players',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('canonical_player_id', db.Integer, db.ForeignKey('canonical_players.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True, nullable=False)
    email = db.Column(db.String(120), index=True, unique=True, nullable=False)
    password_hash = db.Column(db.String(256))

    tracked_teams = db.relationship(
        'CanonicalTeam', secondary=user_tracked_teams, lazy='dynamic',
        back_populates='tracked_by_users')

    tracked_players = db.relationship(
        'CanonicalPlayer', secondary=user_tracked_players, lazy='dynamic',
        back_populates='tracked_by_users')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_tracking_team(self, team):
        return self.tracked_teams.filter(
            user_tracked_teams.c.canonical_team_id == team.id).count() > 0

    def track_team(self, team):
        if not self.is_tracking_team(team):
            self.tracked_teams.append(team)

    def untrack_team(self, team):
        if self.is_tracking_team(team):
            self.tracked_teams.remove(team)

    def is_tracking_player(self, player):
        return self.tracked_players.filter(
            user_tracked_players.c.canonical_player_id == player.id).count() > 0

    def track_player(self, player):
        if not self.is_tracking_player(player):
            self.tracked_players.append(player)

    def untrack_player(self, player):
        if self.is_tracking_player(player):
            self.tracked_players.remove(player)

    def __repr__(self):
        return f'<User {self.username}>'


class League(db.Model):
    __tablename__ = 'leagues'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    league_id = db.Column(db.String(50), nullable=False)
    image = db.Column(db.String(200))
    last_updated = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)

    canonical_teams = relationship('CanonicalTeam', back_populates='league')
    canonical_players = relationship('CanonicalPlayer', back_populates='league')
    events = relationship('Event', back_populates='league', cascade="all, delete-orphan")

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
    name = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    champion = db.Column(db.String(50), nullable=False)
    gold = db.Column(db.Integer, nullable=False)
    level = db.Column(db.Integer, nullable=False)
    kills = db.Column(db.Integer, nullable=False)
    deaths = db.Column(db.Integer, nullable=False)
    assists = db.Column(db.Integer, nullable=False)
    creeps = db.Column(db.Integer, nullable=False)

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
    tracked_by_users = db.relationship(
        'User', secondary=user_tracked_teams, lazy='dynamic',
        back_populates='tracked_teams')

    def get_latest_event(self):
        # Query for the latest event, return an optimized query
        latest_event = Event.query.join(Match).join(MatchTeam).filter(
            MatchTeam.canonical_team_id == self.id
        ).options(
            joinedload(Event.match)
            .joinedload(Match.games)
            .joinedload(Game.gameTeams)
            .joinedload(GameTeam.gamePlayers)
        ).order_by(desc(Event.start_time_datetime)).first()
        return latest_event

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
    tracked_by_users = db.relationship(
        'User', secondary=user_tracked_players, lazy='dynamic',
        back_populates='tracked_players')

    def get_latest_event(self):
        latest_event = Event.query.join(Match).join(MatchTeam).join(MatchPlayer).filter(
            MatchPlayer.canonical_player_id == self.id
        ).options(
            joinedload(Event.match)
            .joinedload(Match.games)
            .joinedload(Game.gameTeams)
            .joinedload(GameTeam.gamePlayers)
        ).order_by(desc(Event.start_time_datetime)).first()
        return latest_event