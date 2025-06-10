from flask import render_template, url_for, redirect, flash, request, jsonify
from flask_login import current_user, login_user, logout_user, login_required
from lolesports_api.rest_adapter import RestAdapter
from app.models import *
from app import app, db, cache
from app.forms import LoginForm, RegistrationForm, EmptyForm
from urllib.parse import urlsplit

lolapi = RestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')


# --- Helper functions ---

# Caches a user's tracked teams and tracked players
@cache.cached(timeout=3600, key_prefix='dashboard_data_%s')  # Cache for 1 hour
def _get_latest_events_for_entities(user_id):
    app.logger.info(f"CACHE MISS: Running optimized query for user {user_id}")
    user = User.query.get(user_id)
    if not user:
        return {}, {}

    tracked_team_ids = [team.id for team in user.tracked_teams]
    tracked_player_ids = [player.id for player in user.tracked_players]

    if not tracked_team_ids and not tracked_player_ids:
        return {}, {}

    all_latest_event_ids = set()

    # Find latest events for tracked teams
    if tracked_team_ids:
        team_subquery = db.session.query(
            Event.id,
            db.func.row_number().over(
                partition_by=MatchTeam.canonical_team_id,
                order_by=desc(Event.start_time_datetime)
            ).label('rn')
        ).join(Match, Event.id == Match.event_id) \
            .join(MatchTeam, Match.id == MatchTeam.match_id) \
            .filter(MatchTeam.canonical_team_id.in_(tracked_team_ids)).subquery()
        team_event_ids = db.session.query(team_subquery.c.id).filter(team_subquery.c.rn == 1).all()
        all_latest_event_ids.update([eid[0] for eid in team_event_ids])

    # Find latest events for tracked players
    if tracked_player_ids:
        player_subquery = db.session.query(
            Event.id,
            db.func.row_number().over(
                partition_by=MatchPlayer.canonical_player_id,
                order_by=desc(Event.start_time_datetime)
            ).label('rn')
        ).join(Match, Event.id == Match.event_id) \
            .join(MatchTeam, Match.id == MatchTeam.match_id) \
            .join(MatchPlayer, MatchTeam.id == MatchPlayer.match_team_id) \
            .filter(MatchPlayer.canonical_player_id.in_(tracked_player_ids)).subquery()
        player_event_ids = db.session.query(player_subquery.c.id).filter(player_subquery.c.rn == 1).all()
        all_latest_event_ids.update([eid[0] for eid in player_event_ids])

    if not all_latest_event_ids:
        return {}, {}

    # Fetch all needed events and their related data in one query
    events = Event.query.filter(Event.id.in_(list(all_latest_event_ids))).options(
        joinedload(Event.match)
        .joinedload(Match.match_teams)
        .joinedload(MatchTeam.canonical_team),
        joinedload(Event.match)
        .joinedload(Match.match_teams)
        .joinedload(MatchTeam.match_players)
        .joinedload(MatchPlayer.canonical_player),
        joinedload(Event.match)
        .joinedload(Match.games)
        .joinedload(Game.gameTeams)
        .joinedload(GameTeam.gamePlayers)
    ).all()

    # Organize the results into maps for easy lookup
    team_event_map = {}
    player_event_map = {}
    for event in events:
        for mt in event.match.match_teams:
            if mt.canonical_team_id in tracked_team_ids:
                team_event_map[mt.canonical_team_id] = event
            for mp in mt.match_players:
                if mp.canonical_player_id in tracked_player_ids:
                    player_event_map[mp.canonical_player_id] = event

    return team_event_map, player_event_map


@app.route('/login', methods=['GET', 'POST'])
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


@app.route('/register', methods=['GET', 'POST'])
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

@app.route('/logout')
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    form = EmptyForm()

    # Retrieve info from cache
    team_event_map, player_event_map = _get_latest_events_for_entities(current_user.id)

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


@app.route('/')
def index():
    return redirect(url_for('login'))
@app.route('/leagues')
def leagues():
    to_display = League.query.all()
    return render_template('leagues.html', leagues=to_display)

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
    event = db.get_or_404(Event, id)
    form = EmptyForm()
    if event.match is None:
        flash("Match details for this event have not been seeded yet. Please check back later.", "info")
        return render_template('match.html', title="Upcoming Match", event=event, teams=[], games=[], form=form)
    teams_to_display = event.match.match_teams
    games_to_display = event.match.games
    return  render_template('match.html', title='Match Details', games=games_to_display, teams=teams_to_display, event=event, form=form)

@app.route('/track_team/<int:team_id>', methods=['POST'])
@login_required
def track_team(team_id):
    form = EmptyForm()
    if form.validate_on_submit():
        team = db.get_or_404(CanonicalTeam, team_id)
        current_user.track_team(team)
        db.session.commit()
        cache.delete(f'dashboard_data_{current_user.id}')
        return jsonify({'status': 'success', 'action': 'tracked', 'name': team.name})
    return jsonify({'status': 'error', 'message': 'Invalid request.'}), 400


@app.route('/untrack_team/<int:team_id>', methods=['POST'])
@login_required
def untrack_team(team_id):
    form = EmptyForm()
    if form.validate_on_submit():
        team = db.get_or_404(CanonicalTeam, team_id)
        current_user.untrack_team(team)
        db.session.commit()
        cache.delete(f'dashboard_data_{current_user.id}')
        return jsonify({'status': 'success', 'action': 'untracked', 'name': team.name})
    return jsonify({'status': 'error', 'message': 'Invalid request.'}), 400


@app.route('/track_player/<int:player_id>', methods=['POST'])
@login_required
def track_player(player_id):
    form = EmptyForm()
    if form.validate_on_submit():
        player = db.get_or_404(CanonicalPlayer, player_id)
        current_user.track_player(player)
        db.session.commit()
        cache.delete(f'dashboard_data_{current_user.id}')
        return jsonify({'status': 'success', 'action': 'tracked', 'name': player.name})
    return jsonify({'status': 'error', 'message': 'Invalid request.'}), 400


@app.route('/untrack_player/<int:player_id>', methods=['POST'])
@login_required
def untrack_player(player_id):
    form = EmptyForm()
    if form.validate_on_submit():
        player = db.get_or_404(CanonicalPlayer, player_id)
        current_user.untrack_player(player)
        db.session.commit()
        cache.delete(f'dashboard_data_{current_user.id}')
        return jsonify({'status': 'success', 'action': 'untracked', 'name': player.name})
    return jsonify({'status': 'error', 'message': 'Invalid request.'}), 400

@app.route('/untrack_all_teams', methods=['POST'])
@login_required
def untrack_all_teams():
    form = EmptyForm()
    if form.validate_on_submit():
        current_user.tracked_teams = []
        db.session.commit()
        cache.delete(f'dashboard_data_{current_user.id}')
        flash('You are no longer tracking any teams.', 'info')
    return redirect(url_for('dashboard'))

@app.route('/untrack_all_players', methods=['POST'])
@login_required
def untrack_all_players():
    form = EmptyForm()
    if form.validate_on_submit():
        current_user.tracked_players = []
        db.session.commit()
        cache.delete(f'dashboard_data_{current_user.id}')
        flash('You are no longer tracking any players.', 'info')
    return redirect(url_for('dashboard'))