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
            for event in eventSchedule.events:
                if db.session.query(Event).filter_by(match_id=event.match_id).first() is None:
                    e_to_add = Event(start_time=event.start_time, strategy=event.strategy, state=event.state, match_id=event.match_id,
                              team_one=event.teams[0].get('name'), team_two=event.teams[1].get('name'))
                    league.events.append(e_to_add)
                    db.session.add(e_to_add)
            db.session.commit()
            app.logger.debug("finished seeding league: %s" % league.league_name)
            time.sleep(.25)
        update_completed_matches()

def update_completed_matches():
    with app.app_context():
        all_events = Event.query.all()
        for event in all_events:
            if not event.match:
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
                app.logger.warning("Finished seeding match in League: %d, Event:  %d, Match: %d" % (event.league.id, event.id, event.match.id))
            else:
                app.logger.warning("MATCH ALREADY UPDATED %s" % event.match_id)
            time.sleep(.1)

scheduler.add_job(update_leagues, 'interval', minutes=10, next_run_time=datetime.now())