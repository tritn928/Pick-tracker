from app import app
from app import db
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone, timedelta
from lolesports_api.rest_adapter import RestAdapter
from app.models import *
from apscheduler.executors.pool import ThreadPoolExecutor
import time
from pytz import timezone as tz

executors = {
    'default': ThreadPoolExecutor(max_workers=20)
}

lolapi = RestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')
scheduler = BackgroundScheduler()

# Add Events to every League
def update_leagues():
    with app.app_context():
        all_leagues = League.query.all()
        for league in all_leagues:
            eventSchedule = lolapi.get_schedule(league.name, league.league_id)
            for event in eventSchedule.events:
                target = db.session.query(Event).filter_by(match_id=event.match_id).first()
                if target is None:
                    e_to_add = Event(start_time=event.start_time, strategy=event.strategy, state=event.state, match_id=event.match_id,
                              team_one=event.teams[0].get('name'), team_two=event.teams[1].get('name'))
                    league.events.append(e_to_add)
                    db.session.add(e_to_add)
            db.session.commit()
            time.sleep(.4)

# Don't know if this is faster or not
def do_half():
    for i in range(1, 10):
        update_league(i)
        time.sleep(20)

def do_rest():
    for i in range(10, 34):
        update_league(i)
        time.sleep(20)

# Updates all events for one league.
# Creates a match with teams/players info
# If the match has any games completed, also add those stats to the match
def update_league(id:int):
    with app.app_context():
        all_events = Event.query.filter_by(league_id=id).all()
        for event in all_events:
            update_match(event)
            app.logger.warning("Finished seeding match in League: %d, Event:  %d, Match: %d" % (event.league.id, event.id, event.match.id))
            time.sleep(.2)

# Handles updating the match details
def update_match(event: Event):
    cur_match = lolapi.get_match(event.match_id)
    if event.match is None or not event.match.teams or event.match.teams[0].name == 'TBD' or event.match.teams[1].name == 'TBD':
        #TODO: update everything properly instead of deleting and recreating
        if event.match:
            db.session.delete(event.match)
        db.session.commit()
        to_add = Match(team_one_id=cur_match.team_ids[0], team_two_id=cur_match.team_ids[1])
        event.match = to_add
        db.session.add(to_add)
        if event.match.match_teams:
            for old_team in list(event.match.match_teams):
                db.session.delete(old_team)
            db.session.commit()
        teams = lolapi.get_teams([event.match.team_one_id, event.match.team_two_id])
        team_one = MatchTeam(name=teams[0]['name'], image=teams[0]['image'])
        team_two = MatchTeam(name=teams[1]['name'], image=teams[1]['image'])
        event.match.teams.append(team_one)
        event.match.teams.append(team_two)
        event.team_one = team_one.name
        event.team_two = team_two.name
        db.session.add(team_one)
        db.session.add(team_two)
        for i in range(len(teams)):
            for player in teams[i]['players']:
                p_to_add = MatchPlayer(team_id=event.match.teams[i].id, name=player['summonerName'], role=player['role'])
                event.match.teams[i].players.append(p_to_add)
                db.session.add(p_to_add)
    if not event.match.games:
        app.logger.warning("match has no games, creating all games available")
        # if there are no games at all
        for game in cur_match.games:
            g_to_add = Game(game_id=game.id)
            event.match.games.append(g_to_add)
            db.session.add(g_to_add)
            for team in game.teams:
                team_name = "TBD"
                if team.team_id == event.match.team_one_id:
                    team_name = event.team_one
                else:
                    team_name = event.team_two
                gT_to_add = GameTeam(team_id=team.team_id, team_name=team_name)
                event.match.games[-1].gameTeams.append(gT_to_add)
                db.session.add(gT_to_add)
                for player in team.players:
                    gP_to_add = GamePlayerPerformance(name=player.name, role=player.role,
                                            champion=player.champion,
                                            gold=player.gold,
                                            level=player.level,
                                            kills=player.kills,
                                            deaths=player.deaths,
                                            assists=player.assists,
                                            creeps=player.creeps)
                    event.match.games[-1].gameTeams[-1].gamePlayers.append(gP_to_add)
                    db.session.add(gP_to_add)
            event.state = cur_match.state
        db.session.commit()
    elif len(event.match.games) != len(cur_match.games):
        app.logger.warning("Match does not have all games, updating old games, adding new games")
        to_make = len(cur_match.games) - len(event.match.games)
        to_update = len(cur_match.games) - to_make
        for i in range(0, to_update):
            game = cur_match.games[i]
            g_to_update = Game.query.filter_by(game_id=game.id).first()
            for i in range(0, 2):
                gT_to_update = g_to_update.gameTeams[i]
                for j in range(0, 5):
                    player = game.teams[i].players[j]
                    gP_to_update = gT_to_update.gamePlayers[j]
                    gP_to_update.champion = player.champion
                    gP_to_update.gold = player.gold
                    gP_to_update.level = player.level
                    gP_to_update.kills = player.kills
                    gP_to_update.deaths = player.deaths
                    gP_to_update.assists = player.assists
                    gP_to_update.creeps = player.creeps
        for i in range(to_update, len(cur_match.games)):
            game = cur_match.games[i]
            g_to_add = Game(game_id=game.id)
            event.match.games.append(g_to_add)
            db.session.add(g_to_add)
            for team in game.teams:
                gT_to_add = GameTeam(test=2)
                event.match.games[-1].gameTeams.append(gT_to_add)
                db.session.add(gT_to_add)
                for player in team.players:
                    gP_to_add = GamePlayerPerformance(name=player.name, role=player.role,
                                           champion=player.champion,
                                           gold=player.gold,
                                           level=player.level,
                                           kills=player.kills,
                                           deaths=player.deaths,
                                           assists=player.assists,
                                           creeps=player.creeps)
                    event.match.games[-1].gameTeams[-1].gamePlayers.append(gP_to_add)
                    db.session.add(gP_to_add)
            event.state = cur_match.state
        db.session.commit()
    else:
        app.logger.warning("Match already exists, updating stats if not completed")
        for game in cur_match.games:
            g_to_update = Game.query.filter_by(game_id=game.id).first()
            for i in range(0, 2):
                gT_to_update = g_to_update.gameTeams[i]
                for j in range(0, 5):
                    player = game.teams[i].players[j]
                    gP_to_update = gT_to_update.gamePlayers[j]
                    gP_to_update.champion = player.champion
                    gP_to_update.gold = player.gold
                    gP_to_update.level = player.level
                    gP_to_update.kills = player.kills
                    gP_to_update.deaths = player.deaths
                    gP_to_update.assists = player.assists
                    gP_to_update.creeps = player.creeps
        event.state = cur_match.state
    db.session.commit()

# Handles updating events that are unstarted
# Schedules an update match job for their start time
def update_unstarted():
    current_time = datetime.now(timezone.utc)
    threshold = timedelta(seconds=10)
    with app.app_context():
        unstarted_events = Event.query.filter_by(state='unstarted').all()
        for unstarted_event in unstarted_events:
            start_time = unstarted_event.start_time
            start_time = datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if current_time > start_time:
                app.logger.warning("Event %d in League %d has passed starting time %s, updating" % (unstarted_event.id, unstarted_event.league.id, start_time))
                unstarted_event.last_updated = current_time
                update_match(unstarted_event)
            else:
                app.logger.warning("Event %d in League %d has not started, not updating until %s" % (unstarted_event.id,
                                    unstarted_event.league.id, start_time))
                scheduler.add_job(update_match, trigger='date', run_date=start_time, args=[unstarted_event])
        app.logger.warning("finished updating matches unstarted")

def f_update_unstarted():
    current_time = datetime.now(timezone.utc)
    threshold = timedelta(minutes=5)
    with app.app_context():
        unstarted_events = Event.query.filter_by(state='unstarted').all()
        for unstarted_event in unstarted_events:
            start_time = unstarted_event.start_time
            start_time = datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if (current_time - unstarted_event.last_updated.replace(tzinfo=timezone.utc)) > threshold:
                app.logger.warning("Event %d in League %d has passed threshold %s, updating" % (unstarted_event.id, unstarted_event.league.id, start_time))
                unstarted_event.last_updated = current_time
                update_match(unstarted_event)
        app.logger.warning("finished updating matches unstarted")

# Handles updating events in progress
# Updates each match once every 10 seconds
def update_in_progress():
    current_time = datetime.now(timezone.utc)
    threshold = timedelta(seconds=10)
    with app.app_context():
        in_progress_events = Event.query.filter_by(state='inProgress').all()
        for in_progress_event in in_progress_events:
            difference = current_time - in_progress_event.last_updated.replace(tzinfo=tz('UTC'))
            if difference > threshold:
                app.logger.warning("Event %d in League %d is in progress, updating" % (in_progress_event.id, in_progress_event.league.id))
                update_match(in_progress_event)
        app.logger.warning("finished updating matches in progress")

def print_jobs():
    all_jobs = scheduler.get_jobs()
    for job in all_jobs:
        print(f"Last Job ID: {job.id} | Function: {job.func} | Next Run Time: {job.next_run_time}")

#scheduler.add_job(update_leagues, 'interval', minutes=40, next_run_time=datetime.now())
scheduler.add_job(update_unstarted, trigger='date', run_date=datetime.now())
scheduler.add_job(update_in_progress, 'interval', minutes=1, next_run_time=datetime.now())
#scheduler.add_job(do_half, trigger='interval', minutes=45, next_run_time=datetime.now() + timedelta(minutes=1))
#scheduler.add_job(do_rest, trigger='interval', minutes=45, next_run_time=datetime.now() + timedelta(minutes=2))
scheduler.add_job(print_jobs, 'interval', minutes=3, next_run_time=datetime.now() + timedelta(minutes=1))
scheduler.add_job(f_update_unstarted, trigger='interval', minutes=5, next_run_time=datetime.now() + timedelta(minutes=1))