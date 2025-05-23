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
    if event.match is None:
        app.logger.warning("event has no match, getting match")
        cur_match = lolapi.get_match(event.match_id)
        to_add = Match(team_one_id=cur_match.team_ids[0], team_two_id=cur_match.team_ids[1])
        event.match = to_add
        db.session.add(to_add)
        teams = lolapi.get_teams([event.match.team_one_id, event.match.team_two_id])
        team_one = Team(name=teams[0]['name'])
        team_two = Team(name=teams[1]['name'])
        event.match.teams.append(team_one)
        event.match.teams.append(team_two)
        db.session.add(team_one)
        db.session.add(team_two)
        for i in range(len(teams)):
            for player in teams[i]['players']:
                p_to_add = Player(name=player['summonerName'], role=player['role'])
                event.match.teams[i].players.append(p_to_add)
                db.session.add(p_to_add)
        for game in cur_match.games:
            g_to_add = Game(test=1)
            event.match.games.append(g_to_add)
            db.session.add(g_to_add)
            for team in game.teams:
                gT_to_add = GameTeam(test=2)
                event.match.games[-1].gameTeams.append(gT_to_add)
                db.session.add(gT_to_add)
                for player in team.players:
                    gP_to_add = GamePlayer(name=player.name, role=player.role,
                                    champion=player.champion,
                                    gold=player.gold,
                                    level=player.level,
                                    kills=player.kills,
                                    deaths=player.deaths,
                                    assists=player.assists,
                                    creeps=player.creeps)
                    event.match.games[-1].gameTeams[-1].gamePlayers.append(gP_to_add)
                    db.session.add(gP_to_add)
        db.session.commit()
    teams_to_display = event.match.teams
    games_to_display = event.match.games
    return  render_template('match.html', games=games_to_display, teams=teams_to_display, event=event)