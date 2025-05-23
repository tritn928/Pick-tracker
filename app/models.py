from sqlalchemy.orm import relationship
from app import db
from datetime import datetime, timezone

class League(db.Model):
    __tablename__ = 'leagues'
    id = db.Column(db.Integer, primary_key=True)
    league_name = db.Column(db.String(50), nullable=False)
    league_id = db.Column(db.String(50), nullable=False)
    last_updated = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)

    events = relationship('Event', back_populates='league')

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
    match = relationship('Match', back_populates='event', uselist=False)

class Match(db.Model):
    __tablename__ = 'matches'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    team_one_id = db.Column(db.String(50), nullable=False)
    team_two_id = db.Column(db.String(50), nullable=False)

    event = relationship('Event', foreign_keys=[event_id], back_populates='match', uselist=False)
    teams = relationship('Team', back_populates='match')
    games = relationship('Game', back_populates='match')

class Team(db.Model):
    __tablename__ = 'teams'

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    name = db.Column(db.String(50), nullable=False)

    match = relationship('Match', back_populates='teams')
    players = relationship('Player', back_populates='team')

class Player(db.Model):
    __tablename__ = 'players'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(50), nullable=False)

    team = relationship('Team', back_populates='players')

class Game(db.Model):
    __tablename__ = 'games'

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    test = db.Column(db.Integer, nullable=False)

    match = relationship('Match', back_populates='games')
    gameTeams = relationship('GameTeam', back_populates='game')

class GameTeam(db.Model):
    __tablename__ = 'gameteams'

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey('games.id'), nullable=False)
    test = db.Column(db.Integer, nullable=False)

    game = relationship('Game', back_populates='gameTeams')
    gamePlayers = relationship('GamePlayer', back_populates='gameTeam')

class GamePlayer(db.Model):
    __tablename__ = 'gameplayers'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('gameteams.id'), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    champion = db.Column(db.String(50), nullable=False)
    gold = db.Column(db.Integer, nullable=False)
    level = db.Column(db.Integer, nullable=False)
    kills = db.Column(db.Integer, nullable=False)
    deaths = db.Column(db.Integer, nullable=False)
    assists = db.Column(db.Integer, nullable=False)
    creeps = db.Column(db.Integer, nullable=False)

    gameTeam = relationship('GameTeam', back_populates='gamePlayers')