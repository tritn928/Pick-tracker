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
    # Call the cached function to get all tracked items
    all_tracked_items = get_dashboard_data(current_user.id)

    # Separate the items into two lists for the template
    tracked_teams = [item for item in all_tracked_items if item.team]
    tracked_players = [item for item in all_tracked_items if item.player]

    return render_template('dashboard.html', title='Dashboard',
                           tracked_teams=tracked_teams,
                           tracked_players=tracked_players,
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

@current_app.route('/track_team/<int:team_id>/in_event/<int:event_id>', methods=['POST'])
@login_required
def track_team(team_id, event_id):
    form = EmptyForm()
    if form.validate_on_submit():
        team = db.get_or_404(CanonicalTeam, team_id)
        event = db.get_or_404(Event, event_id)
        current_user.track(event, team=team)
        db.session.commit()
        cache.delete_memoized(get_dashboard_data, current_user.id)
        return jsonify({'status': 'success', 'action': 'tracked', 'name': team.name})
    return jsonify({'status': 'error', 'message': 'Invalid request.'}), 400

@current_app.route('/untrack_team/<int:team_id>/in_event/<int:event_id>', methods=['POST'])
@login_required
def untrack_team(team_id, event_id):
    form = EmptyForm()
    if form.validate_on_submit():
        team = db.get_or_404(CanonicalTeam, team_id)
        event = db.get_or_404(Event, event_id)
        current_user.untrack(event, team=team)
        db.session.commit()
        cache.delete_memoized(get_dashboard_data, user_id=current_user.id)
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error'}), 400


@current_app.route('/untrack_item/<int:item_id>', methods=['POST'])
@login_required
def untrack_item(item_id):
    form = EmptyForm()
    if form.validate_on_submit():
        current_user.untrack_item_by_id(item_id)
        db.session.commit()
        cache.delete_memoized(get_dashboard_data, user_id=current_user.id)
        return jsonify({'status': 'success', 'message': 'Item untracked.'})
    return jsonify({'status': 'error', 'message': 'Invalid request.'}), 400


@current_app.route('/track_player/<int:player_id>/in_event/<int:event_id>', methods=['POST'])
@login_required
def track_player(player_id, event_id):
    form = EmptyForm()
    if form.validate_on_submit():
        player = db.get_or_404(CanonicalPlayer, player_id)
        event = db.get_or_404(Event, event_id)
        current_user.track(event, player=player)
        db.session.commit()
        cache.delete_memoized(get_dashboard_data, current_user.id)
        return jsonify({'status': 'success', 'action': 'tracked', 'name': player.name})
    return jsonify({'status': 'error', 'message': 'Invalid request.'}), 400

@current_app.route('/untrack_player/<int:player_id>/in_event/<int:event_id>', methods=['POST'])
@login_required
def untrack_player(player_id, event_id):
    form = EmptyForm()
    if form.validate_on_submit():
        player = db.get_or_404(CanonicalPlayer, player_id)
        event = db.get_or_404(Event, event_id)
        current_user.untrack(event, player=player)
        db.session.commit()
        cache.delete_memoized(get_dashboard_data, user_id=current_user.id)
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error'}), 400



@current_app.route('/untrack_all_teams', methods=['POST'])
@login_required
def untrack_all_teams():
    form = EmptyForm()
    if form.validate_on_submit():
        # Perform a bulk delete on UserTrackedItem records that are for teams
        UserTrackedItem.query.filter_by(
            user_id=current_user.id,
            canonical_player_id=None  # Target team tracks
        ).delete(synchronize_session=False)
        db.session.commit()
        cache.delete_memoized(get_dashboard_data, user_id=current_user.id)
        flash('You are no longer tracking any teams.', 'info')
    return redirect(url_for('dashboard'))

@current_app.route('/untrack_all_players', methods=['POST'])
@login_required
def untrack_all_players():
    form = EmptyForm()
    if form.validate_on_submit():
        # Perform a bulk delete on UserTrackedItem records that are for players
        UserTrackedItem.query.filter_by(
            user_id=current_user.id,
            canonical_team_id=None  # Target player tracks
        ).delete(synchronize_session=False)

        db.session.commit()
        cache.delete_memoized(get_dashboard_data, user_id=current_user.id)
        flash('You are no longer tracking any players.', 'info')
    return redirect(url_for('dashboard'))
