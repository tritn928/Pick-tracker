from flask import render_template
from lolesports_api.rest_adapter import RestAdapter
from app.models import League, Event, Match, Team, Player, Game, GameTeam, GamePlayer
from app import db
from app import app
from app.scheduler import scheduler
from datetime import datetime
import time

lolapi = RestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')
@app.route('/')
@app.route('/index')
def index():
    to_display = League.query.all()
    return render_template('index.html', leagues=to_display)

@app.route('/leagues/<int:id>')
def show_league(id):
    league = League.query.get(id)
    to_display = Event.query.filter_by(league_id=league.id).order_by(Event.start_time.desc()).all()
    return render_template('events.html', events=to_display)

@app.route('/events/<int:id>')
def show_event(id):
    event = Event.query.get(id)
    if not event.match:
        cur_match = lolapi.get_match(event.match_id)
        app.logger.warning('api-call: get_match')
        event.match = Match(team_one_id=cur_match.team_ids[0], team_two_id=cur_match.team_ids[1])
        teams = lolapi.get_teams([event.match.team_one_id, event.match.team_two_id])
        app.logger.warning('api-call: get_teams')
        event.match.teams.append(Team(name=teams[0]['name']))
        event.match.teams.append(Team(name=teams[1]['name']))
        for i in range(len(teams)):
            for player in teams[i]['players']:
                event.match.teams[i].players.append(Player(name=player['summonerName'], role=player['role']))
        for game in cur_match.games:
            event.match.games.append(Game(test=1))
            for team in game.teams:
                event.match.games[-1].gameTeams.append(GameTeam(test=2))
                for player in team.players:
                    event.match.games[-1].gameTeams[-1].gamePlayers.append(
                        GamePlayer(name=player.name, role=player.role,
                                    champion=player.champion,
                                    gold=player.gold,
                                    level=player.level,
                                    kills=player.kills,
                                    deaths=player.deaths,
                                    assists=player.assists,
                                    creeps=player.creeps))
        db.session.commit()
    teams_to_display = event.match.teams
    games_to_display = event.match.games
    return  render_template('match.html', games=games_to_display, teams=teams_to_display, event=event)