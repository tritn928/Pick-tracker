from sqlalchemy.orm import relationship
from app import db
from datetime import datetime, timezone

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
    strategy = db.Column(db.Integer, nullable=False)
    state = db.Column(db.String(50), nullable=False)
    match_id = db.Column(db.String(50), nullable=False)
    team_one = db.Column(db.String(50), nullable=False)
    team_two = db.Column(db.String(50), nullable=False)
    last_updated = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)

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
    canonical_team_id = db.Column(db.Integer, db.ForeignKey('canonical_teams.id'), nullable=False)
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

class CanonicalPlayer(db.Model):
    __tablename__ = 'canonical_players'

    id = db.Column(db.Integer, primary_key=True)
    league_id = db.Column(db.Integer, db.ForeignKey('leagues.id'), nullable=False)
    canonical_team_id = db.Column(db.Integer, db.ForeignKey('canonical_teams.id'), nullable=False)
    external_id = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    image = db.Column(db.String(200))
    role = db.Column(db.String(50), nullable=False)

    # could use an association table instead of one-to-many relationship here
    league = relationship('League', back_populates='canonical_players')
    canonical_team = relationship('CanonicalTeam', back_populates='canonical_players')
    match_participations = relationship('MatchPlayer', back_populates='canonical_player', cascade="all, delete-orphan")
    game_participations = relationship('GamePlayerPerformance', back_populates='canonical_player', cascade="all, delete-orphan")