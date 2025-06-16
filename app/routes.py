from flask import render_template, url_for, redirect, flash, request, jsonify, current_app
from flask_login import current_user, login_user, logout_user, login_required
from lolesports_api.rest_adapter import RestAdapter
from app.models import *
from app import db, cache
from app.forms import LoginForm, RegistrationForm, EmptyForm
from urllib.parse import urlsplit
from app.logic import get_dashboard_data

lolapi = RestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')


@current_app.route('/login', methods=['GET', 'POST'])
def login():
    # If the user is already logged in, redirect them to the dashboard
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        # Query user by username
        user = User.query.filter_by(username=form.username.data).first()

        # Check if user exists and if the password is correct
        if user is None or not user.check_password(form.password.data):
            flash('Invalid username or password', 'danger')
            return redirect(url_for('login'))

        login_user(user, remember=form.remember_me.data)

        next_page = request.args.get('next')
        if not next_page or urlsplit(next_page).netloc != '':
            next_page = url_for('dashboard')
        flash(f'Welcome back, {user.username}!', 'success')
        return redirect(next_page)

    return render_template('login.html', title='Sign In', form=form)


@current_app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Congratulations, you are now a registered user!', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', title='Register', form=form)

@current_app.route('/logout')
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


@current_app.route('/dashboard')
@login_required
def dashboard():
    form = EmptyForm()

    # Retrieve info from cache
    team_event_map, player_event_map = get_dashboard_data(current_user.id)

    # Build the lists for the template using the pre-fetched data
    tracked_teams_with_events = [
        (team, team_event_map.get(team.id))
        for team in current_user.tracked_teams
    ]

    tracked_players_with_events = [
        (player, player_event_map.get(player.id))
        for player in current_user.tracked_players
    ]

    # Unstarted events are first
    def sort_key(item):
        latest_event = item[1]
        if not latest_event: return (2, None)
        is_unstarted = 0 if latest_event.state == 'unstarted' else 1
        return (is_unstarted, latest_event.start_time_datetime)

    tracked_teams_with_events.sort(key=sort_key)
    tracked_players_with_events.sort(key=sort_key)

    return render_template('dashboard.html', title='Dashboard',
                           tracked_teams=tracked_teams_with_events,
                           tracked_players=tracked_players_with_events,
                           form=form)


@current_app.route('/')
def index():
    return redirect(url_for('login'))
@current_app.route('/leagues')
def leagues():
    to_display = League.query.all()
    return render_template('leagues.html', leagues=to_display)

@current_app.route('/leagues/<int:id>')
def show_league(id):
    league = League.query.get(id)
    unstarted_events = Event.query.filter_by(league_id=league.id, state='unstarted').order_by(Event.start_time.desc()).all()
    inProgress_events = Event.query.filter_by(league_id=league.id, state='inProgress').order_by(
        Event.start_time.desc()).all()
    completed_events = Event.query.filter_by(league_id=league.id, state='completed').order_by(
        Event.start_time.desc()).all()
    return render_template('events.html', league=league, inProgress_events=inProgress_events, unstarted_events=unstarted_events, completed_events=completed_events)

@current_app.route('/events/<int:id>')
def show_event(id):
    event = db.get_or_404(Event, id)
    form = EmptyForm()
    if event.match is None:
        flash("Match details for this event have not been seeded yet. Please check back later.", "info")
        return render_template('match.html', title="Upcoming Match", event=event, teams=[], games=[], form=form)
    teams_to_display = event.match.match_teams
    games_to_display = event.match.games
    return  render_template('match.html', title='Match Details', games=games_to_display, teams=teams_to_display, event=event, form=form)

@current_app.route('/track_team/<int:team_id>', methods=['POST'])
@login_required
def track_team(team_id):
    form = EmptyForm()
    if form.validate_on_submit():
        team = db.get_or_404(CanonicalTeam, team_id)
        current_user.track_team(team)
        db.session.commit()
        cache.delete_memoized(get_dashboard_data, current_user.id)
        return jsonify({'status': 'success', 'action': 'tracked', 'name': team.name})
    return jsonify({'status': 'error', 'message': 'Invalid request.'}), 400


@current_app.route('/untrack_team/<int:team_id>', methods=['POST'])
@login_required
def untrack_team(team_id):
    form = EmptyForm()
    if form.validate_on_submit():
        team = db.get_or_404(CanonicalTeam, team_id)
        current_user.untrack_team(team)
        db.session.commit()
        cache.delete_memoized(get_dashboard_data, current_user.id)
        return jsonify({'status': 'success', 'action': 'untracked', 'name': team.name})
    return jsonify({'status': 'error', 'message': 'Invalid request.'}), 400


@current_app.route('/track_player/<int:player_id>', methods=['POST'])
@login_required
def track_player(player_id):
    form = EmptyForm()
    if form.validate_on_submit():
        player = db.get_or_404(CanonicalPlayer, player_id)
        current_user.track_player(player)
        db.session.commit()
        cache.delete_memoized(get_dashboard_data, current_user.id)
        return jsonify({'status': 'success', 'action': 'tracked', 'name': player.name})
    return jsonify({'status': 'error', 'message': 'Invalid request.'}), 400


@current_app.route('/untrack_player/<int:player_id>', methods=['POST'])
@login_required
def untrack_player(player_id):
    form = EmptyForm()
    if form.validate_on_submit():
        player = db.get_or_404(CanonicalPlayer, player_id)
        current_user.untrack_player(player)
        db.session.commit()
        cache.delete_memoized(get_dashboard_data, current_user.id)
        return jsonify({'status': 'success', 'action': 'untracked', 'name': player.name})
    return jsonify({'status': 'error', 'message': 'Invalid request.'}), 400

@current_app.route('/untrack_all_teams', methods=['POST'])
@login_required
def untrack_all_teams():
    form = EmptyForm()
    if form.validate_on_submit():
        current_user.tracked_teams = []
        db.session.commit()
        cache.delete_memoized(get_dashboard_data, current_user.id)
        flash('You are no longer tracking any teams.', 'info')
    return redirect(url_for('dashboard'))

@current_app.route('/untrack_all_players', methods=['POST'])
@login_required
def untrack_all_players():
    form = EmptyForm()
    if form.validate_on_submit():
        current_user.tracked_players = []
        db.session.commit()
        cache.delete_memoized(get_dashboard_data, current_user.id)
        flash('You are no longer tracking any players.', 'info')
    return redirect(url_for('dashboard'))