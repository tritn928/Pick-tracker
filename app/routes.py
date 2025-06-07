from flask import render_template
from lolesports_api.rest_adapter import RestAdapter
from app.models import *
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
    unstarted_events = Event.query.filter_by(league_id=league.id, state='unstarted').order_by(Event.start_time.desc()).all()
    inProgress_events = Event.query.filter_by(league_id=league.id, state='inProgress').order_by(
        Event.start_time.desc()).all()
    completed_events = Event.query.filter_by(league_id=league.id, state='completed').order_by(
        Event.start_time.desc()).all()
    return render_template('events.html', league=league, inProgress_events=inProgress_events, unstarted_events=unstarted_events, completed_events=completed_events)

@app.route('/events/<int:id>')
def show_event(id):
    event = Event.query.get(id)
    if event.match is None:
        app.logger.warning("event has no match, getting match")
        #update_match(event)
    teams_to_display = event.match.match_teams
    games_to_display = event.match.games
    return  render_template('match.html', games=games_to_display, teams=teams_to_display, event=event)