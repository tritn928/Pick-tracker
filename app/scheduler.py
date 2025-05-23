from app import app
from app import db
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from lolesports_api.rest_adapter import RestAdapter
from app.models import League, Event, Match, Team, Player, Game, GameTeam, GamePlayer
import time

lolapi = RestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')
scheduler = BackgroundScheduler()

def update_leagues():
    with app.app_context():
        all_leagues = League.query.all()
        for league in all_leagues:
            eventSchedule = lolapi.get_schedule(league.league_name, league.league_id)
            app.logger.warning('api-call: get_schedule')
            for event in eventSchedule.events:
                if db.session.query(Event).filter_by(match_id=event.match_id).first() is None:
                    league.events.append(
                        Event(start_time=event.start_time, strategy=event.strategy, state=event.state, match_id=event.match_id,
                              team_one=event.teams[0].get('name'), team_two=event.teams[1].get('name')))
            db.session.commit()
            time.sleep(.25)
        update_completed_matches()

def update_completed_matches():
    with app.app_context():
        all_events = Event.query.all()
        for event in all_events:
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
            else:
                app.logger.warning("MATCH ALREADY UPDATED %s" % event.match_id)
            time.sleep(.1)

scheduler.add_job(update_leagues, 'interval', minutes=10, next_run_time=datetime.now())