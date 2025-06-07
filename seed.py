from app import db
from app import app
from lolesports_api.rest_adapter import RestAdapter
from app.models import *
import time

# ignore broken schedule calls
# ignore old leagues
ignore = ['LCL', 'TFT Esports', 'LCS', "King's Duel", 'Worlds Qualifying Series', 'LCO', 'LLA', 'CBLOL']
lolapi = RestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')

# Returns the canonical player associated with the player_data
# Creates and returns a new canonical player if no such player exists
def get_or_create_canonical_player(player_data, related_league, team_to_associate_if_new=None):
    player_external_id = player_data.get('id')
    if not player_external_id:
        app.logger.error(f"Player data missing 'id': {player_data}")
        return None

    canonical_player = CanonicalPlayer.query.filter_by(external_id=player_data['id']).first()

    if not canonical_player:
        app.logger.info(
            f"Creating CanonicalPlayer: {player_data.get('summonerName')} (ID: {player_data['id']})")
        canonical_player = CanonicalPlayer(
            external_id=player_data['id'],
            name = player_data['summonerName'],
            image = player_data['image'],
            role = player_data['role'],
            league = related_league,
        )
        canonical_player.canonical_team = team_to_associate_if_new
        db.session.add(canonical_player)
    return canonical_player

# Returns the canonical team associated with the team_data
# Creates and returns a new canonical team if no such team exists
# Also populates the team with any canonical players associated with the team
def get_or_create_canonical_team(team_data, related_league):
    team_external_id = team_data.get('id')
    if not team_external_id:
        app.logger.error(f"Player data missing 'id': {team_data}")
        return None

    canonical_team = CanonicalTeam.query.filter_by(external_id=team_data['id']).first()
    if not canonical_team:
        app.logger.info(f"Creating Canonical Team: {team_data['name']} (ID: {team_data['id']})")
        canonical_team = CanonicalTeam(
            external_id=team_data['id'],
            name=team_data['name'],
            image=team_data['image'],
            league= related_league
        )
        db.session.add(canonical_team)
        for player in team_data['players']:
            canonical_player = get_or_create_canonical_player(player, related_league,  team_to_associate_if_new=canonical_team)

    return canonical_team

# Seeds all Leagues for a sport
def seed_leagues():
    app.logger.info("Starting to seed leagues...")
    # Using league of legends api
    leaguesList = lolapi.get_leagues()
    to_add = []
    for league in leaguesList:
        if league['name'] in ignore:
            continue
        new_league = League(
                name=league['name'],
                league_id=league['id'],
                image=league['image']
        )
        to_add.append(new_league)
        app.logger.info(f"Added League: {new_league.name}")
    db.session.add_all(to_add)
    db.session.commit()
    app.logger.info("Finished seeding leagues")

# Seeds all Events
def seed_events():
    app.logger.info("Starting to seed events...")
    all_leagues = League.query.all()
    for league in all_leagues:
        app.logger.info(f"Fetching schedule for League: {league.name} (ID: {league.league_id})")
        eventSchedule = lolapi.get_schedule(league.name, league.league_id)
        to_add = []
        for event in eventSchedule.events:
            new_event = Event(
                start_time=event.start_time,
                strategy=event.strategy,
                state=event.state,
                match_id=event.match_id,
                team_one=event.teams[0].get('name'),
                team_two=event.teams[1].get('name'),
                league_id=league.id
            )
            to_add.append(new_event)
            app.logger.info(f"Added Event (MatchID: {new_event.match_id}) in League: {league.name}")
        db.session.add_all(to_add)
        db.session.commit()
        time.sleep(.4)
    app.logger.info("Finished seeding events")

# Seeds all Matches
def seed_matches():
    app.logger.info("Starting to seed matches and their details...")
    all_events_to_process = Event.query.all()
    for event in all_events_to_process:

        app.logger.info(f"Processing Event (PK: {event.id}, API MatchID: {event.match_id}) for match creation.")

        match_details_api = lolapi.get_match(event.match_id)
        new_match = Match(
            event_id=event.id,
            team_one_id=match_details_api.team_ids[0],
            team_two_id=match_details_api.team_ids[1]
        )
        event.match = new_match
        db.session.add(new_match)

        current_match_players_map = {}
        api_teams_in_match = lolapi.get_teams([event.match.team_one_id, event.match.team_two_id])

        # Gets the teams involved in the match
        for api_team_data in api_teams_in_match:
            if api_team_data['name'] == 'TBD':
                # Make a temporary match_team
                match_team = MatchTeam(
                    name='TBD',
                    image=None,
                )
                match_team.match = new_match
                db.session.add(match_team)
                continue
            # Get Canonical Team
            canonical_team = get_or_create_canonical_team(api_team_data, event.league)
            db.session.flush()

            # Create MatchTeam
            match_team = MatchTeam(
                name=canonical_team.name,
                image=canonical_team.image,
            )
            match_team.match = new_match
            match_team.canonical_team = canonical_team
            db.session.add(match_team)

            # Create MatchPlayers
            for api_player_data in api_team_data.get('players', []):
                canonical_player = get_or_create_canonical_player(api_player_data, event.league, canonical_team)
                if canonical_player is None:
                    continue
                match_player = MatchPlayer(
                    name=canonical_player.name,
                    role=api_player_data['role'],
                    image=canonical_player.image,
                )
                match_player.match_team = match_team
                match_player.canonical_player = canonical_player
                db.session.add(match_player)
                current_match_players_map[canonical_player.external_id] = match_player

        # Adds the existing games
        if hasattr(match_details_api, 'games'):
            for api_game_data in match_details_api.games:
                # Create Game Obj
                game_obj = Game(
                    game_id=api_game_data.id
                )
                game_obj.match = new_match
                db.session.add(game_obj)

                # Create GameTeam
                for api_team_in_game in api_game_data.teams:
                    canonical_team_for_game = CanonicalTeam.query.filter_by(
                        external_id=api_team_in_game.team_id).first()
                    game_team = GameTeam(
                        team_id=api_team_in_game.team_id,
                        team_name=canonical_team_for_game.name,
                    )
                    game_team.game = game_obj
                    game_team.canonical_team = canonical_team_for_game
                    db.session.add(game_team)

                    # Create GamePlayers
                    for api_player_stats in api_team_in_game.players:
                        if api_player_stats.id is None:
                            continue

                        # Creates player_data for this specific player
                        player_data_for_creation = {
                            'id': api_player_stats.id,
                            'summonerName': api_player_stats.name,
                            'role': api_player_stats.role,
                            'image': None
                        }
                        # Attempt to retrieve an existing canonical_player
                        # Or create a new canonical_player
                        canonical_player_for_stats = get_or_create_canonical_player(
                            player_data_for_creation,
                            event.league,
                            team_to_associate_if_new=canonical_team_for_game
                        )
                        # Pair the canonical_player with the MatchPlayer in the map
                        match_player_for_stats = current_match_players_map.get(canonical_player_for_stats.external_id)
                        if not match_player_for_stats:
                            # If the current Game player is not a MatchPlayer
                            target_match_team_for_sub = None
                            for mt_in_match in new_match.match_teams:
                                # Iterate over MatchTeams already created for this match
                                # Look for the id that is associated with this MatchTeam
                                if mt_in_match.canonical_team_id == canonical_team_for_game.id or \
                                        (
                                                mt_in_match.canonical_team and mt_in_match.canonical_team.id == canonical_team_for_game.id):
                                    target_match_team_for_sub = mt_in_match
                                    break
                            # If successfully found the MatchTeam, create a MatchPlayer for the sub
                            if target_match_team_for_sub:
                                match_player_for_stats = MatchPlayer(
                                    name=canonical_player_for_stats.name,
                                    role=api_player_stats.role,
                                    image=canonical_player_for_stats.image,
                                )
                                match_player_for_stats.match_team = target_match_team_for_sub
                                match_player_for_stats.canonical_player = canonical_player_for_stats
                                db.session.add(match_player_for_stats)
                                current_match_players_map[str(canonical_player_for_stats.external_id)] = match_player_for_stats
                                app.logger.info(
                                    f"Created MatchPlayer for substitute {canonical_player_for_stats.name} in MatchTeam {target_match_team_for_sub.name}")
                            else:
                                app.logger.error(
                                    f"Could not find MatchTeam for substitute player {canonical_player_for_stats.name} (associated with CTeam {canonical_team_for_game.name}) in Match for Event PK {event.id}. Skipping GPP.")
                                continue

                        db.session.flush()
                        # Add a player's stats for a game and pair it to the MatchPlayer and CanonicalPlayer
                        gpp = GamePlayerPerformance(
                            name=canonical_player_for_stats.name,
                            role=api_player_stats.role,
                            champion=api_player_stats.champion,
                            gold=api_player_stats.gold,
                            level=api_player_stats.level,
                            kills=api_player_stats.kills,
                            deaths=api_player_stats.deaths,
                            assists=api_player_stats.assists,
                            creeps=api_player_stats.creeps,
                            canonical_player_id=canonical_player_for_stats.id,
                            match_player_id=match_player_for_stats.id
                        )
                        match_player = match_player_for_stats if match_player_for_stats else None
                        if hasattr(game_team, 'gamePlayers'): game_team.gamePlayers.append(gpp)
                        if hasattr(canonical_player_for_stats,
                                   'game_performances'): canonical_player_for_stats.game_performances.append(gpp)
                        if match_player_for_stats and hasattr(match_player_for_stats, 'game_stats'):
                            match_player_for_stats.game_stats.append(gpp)
                        db.session.add(gpp)
        db.session.commit()
        app.logger.info(f"Successfully processed and committed Match and details for Event PK: {event.id}")
        time.sleep(0.1)
    app.logger.info("Finished seeding matches and details.")