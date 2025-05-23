from lolesports_api.rest_adapter import RestAdapter
from lolesports_api.models import Match, Schedule
from lolesports_api.slip import Slip, PlayerMapStats
from typing import List, Dict, Any
import time
from datetime import datetime, timedelta

# Retrieves all games from the first page of the lolesports schedule
def get_all_matches(league_name: str, league_id: str, lolapi: RestAdapter) -> Schedule:
    eventSchedule = lolapi.get_schedule(league_name, league_id)
    return eventSchedule

def print_schedule(eventSchedule: Schedule):
    print(eventSchedule)

# Gets all unstarted games
def get_upcoming_matches(league_name: str, league_id: str, lolapi: RestAdapter) -> Schedule:
    eventSchedule = lolapi.get_schedule(league_name, league_id)
    return eventSchedule

def print_matchup(match: Match, lolapi: RestAdapter):
    params = {'hl': 'en-US', 'id': ",".join(map(str, match.team_ids))}
    result = lolapi.get('persisted/gw/getTeams', ep_params=params).data.get('data').get('teams')
    for team in result:
        print(team.get('name'))
        for player in team.get('players'):
            print("%-25s | %-7s | %-20s" % (player.get('summonerName'), player.get('role'), player.get('id')))
        print()

def get_matchup_details(match_id: str, lolapi: RestAdapter) -> Match:
    match = lolapi.get_match(match_id)
    return match

def get_player_details(player_id: str, match: Match) -> Slip.ParlayPlayer | None:
    player_name = player_id
    map_stats = []
    for game in match.games:
        for team in game.teams:
            for player in team.players:
                if player.id == player_id:
                    player_name = player.name
                    map_stats.append(PlayerMapStats(player.kills, player.deaths, player.assists))

    p_player = Slip.ParlayPlayer(player_name, player_id, match, map_stats, 0, 2)
    return p_player

def get_leagues(lolapi: RestAdapter) -> List[Dict]:
    params = {'hl': 'en-US'}
    leaguesList = lolapi.get('persisted/gw/getLeagues', ep_params=params).data.get('data').get('leagues')
    return leaguesList

def print_leagues(leaguesList: List[Dict]):
    for league in leaguesList:
        print(league.get('name') + ' | ' + league.get('id'))

def get_league_id(league_name: str, leagueList: List[Dict]) -> str:
    for league in leagueList:
        if league.get('name') == league_name:
            return league.get('id')
    return ''

def print_and_get_league(leaguesList: List[Dict]) -> (str, str):
    print_leagues(leaguesList)
    league_name = input('Please enter League Name: ')
    league_id = get_league_id(league_name, leaguesList)
    while league_id == '':
        league_name = input('Please reenter League Name: ')
        league_id = get_league_id(league_name, leaguesList)
    return league_name, league_id

def print_and_get_match(eventSchedule: Schedule, lolapi:RestAdapter) -> Match:
    print_schedule(eventSchedule)
    matchup = input('Please enter Matchup ID: ')
    match = get_matchup_details(matchup, lolapi)
    return match

def print_and_get_player(match: Match, lolapi: RestAdapter) -> Slip.ParlayPlayer:
    print_matchup(match, lolapi)
    player_id = input('Please enter Player ID: ')
    return get_player_details(player_id, match)

# Prints out all leagues and their IDs
# Gives the schedule for a specific league
# Gives the matchup details for a matchLC
# Gives player details for a team in the match
def main():
    return
    lolapi = RestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')
    leaguesList = get_leagues(lolapi)
    # display info on leagues
    l_info = print_and_get_league(leaguesList)
    # display the current schedule for the league
    eventSchedule = get_all_matches(l_info[0], l_info[1], lolapi)
    match = print_and_get_match(eventSchedule, lolapi)
    # display details for the selected match
    s = Slip(print_and_get_player(match, lolapi))

    # Loop to select slips
    stay = True
    while stay:
        toDo = ''
        actions = ['p', 'm', 'l', 'r', 'q']
        while toDo not in actions:
            toDo = input(
                '\nEnter p to select another player from this match\nEnter m to select a different match\nEnter l to select a different league\nEnter r to remove a player from your slip\nEnter q to quit: ')
            if toDo == 'p':
                s.add_player(print_and_get_player(match, lolapi))
            elif toDo == 'm':
                match = print_and_get_match(eventSchedule, lolapi)
                s.add_player(print_and_get_player(match, lolapi))
            elif toDo == 'l':
                l_info = print_and_get_league(leaguesList)
                eventSchedule = get_all_matches(l_info[0], l_info[1], lolapi)
                match = print_and_get_match(eventSchedule, lolapi)
                s.add_player(print_and_get_player(match, lolapi))
            elif toDo == 'r':
                for player in s.players:
                    print(player.name)
                    toRemove = input("Please enter the name of the player to remove: ")
                    for look in s.players:
                        if look.name == toRemove:
                            s.players.remove(look)
            elif toDo == 'q':
                print()
                stay = False

    # Loop to update slips
    # TODO: add support for lines and # of maps
    while True:
        # Get all live events
        liveSchedule = lolapi.get_live()
        for i in range(len(s.players)):
            # If slip is completed, do not update
            if s.players[i].current_match.state == 'completed':
                stats = s.players[i].stats_for_all()
                print(f"{s.players[i].name} | {stats.kills} | {stats.deaths} | {stats.assists}")
            # If slip is unstarted, keep checking live events to see when game will start
            elif s.players[i].current_match.state == 'unstarted':
                for event in liveSchedule.events:
                    if event.match_id == s.players[i].current_match.match_id:
                        match = lolapi.get_match(s.players[i].current_match.match_id)
                        s.update_player(s.players[i].id, match)
                        s.players[i] = get_player_details(s.players[i].id, match)
                print(f"{s.players[i].name} | unstarted")
            # If slip is in progress, update
            elif s.players[i].current_match.state == 'inProgress':
                match = lolapi.get_match(s.players[i].current_match.match_id)
                s.update_player(s.players[i].id, match)
                s.players[i] = get_player_details(s.players[i].id, match)
                stats = s.players[i].stats_for_all()
                print(f"{s.players[i].name} | {stats.kills} | {stats.deaths} | {stats.assists}")
        time.sleep(10)

if __name__ == '__main__':
    main()