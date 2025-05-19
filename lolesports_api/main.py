from lolesports_api.rest_adapter import RestAdapter
from lolesports_api.models import Match

# Retrieves all games from the first page of the lolesports schedule
# Prints the score and player details of completed games
def get_all_matches(league_name: str, league_id: str):
    lolapi = RestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')
    eventSchedule = lolapi.get_schedule(league_name, league_id)
    for event in eventSchedule.events:
        # if completed, print out details
        if event.state == 'completed':
            print(event.start_time + ' | ' + event.state + ' | ' + event.match_id + ' | ' + event.teams[0].get(
                'name') + ' vs ' + event.teams[1].get('name')
                  + ' | ' + str(event.teams[0].get('result').get('gameWins')) + "-" +
                  str(event.teams[1].get('result').get('gameWins')))
        # else just print the matchup
        if event.state == 'unstarted':
            print(event.start_time + ' | ' + event.state + ' | ' + event.match_id + ' | ' + event.teams[0].get(
                'name') + ' vs ' + event.teams[1].get('name')
                  + ' | ' + "Best of " + str(event.strategy))

# Gets all unstarted games
def get_upcoming_matches(league_name: str, league_id: str):
    lolapi = RestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')
    eventSchedule = lolapi.get_schedule(league_name, league_id)
    for event in eventSchedule.events:
        if event.state == 'unstarted':
            print(event.start_time + ' | ' + event.state + ' | ' + event.match_id + ' | ' + event.teams[0].get(
                'name') + ' ' + event.teams[0].get('code') + ' vs ' + event.teams[1].get('name') + ' ' + event.teams[1].get('code')
                  + ' | ' + "Best of " + str(event.strategy))

def get_matchup_details(match_id: str) -> Match:
    lolapi = RestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')
    match = lolapi.get_match(match_id)
    params = {'hl': 'en-US', 'id': ",".join(map(str, match.team_ids))}
    result = lolapi.get('persisted/gw/getTeams', ep_params=params).data.get('data').get('teams')
    for team in result:
        print(team.get('name'))
        for player in team.get('players'):
            print("%-25s | %-7s | %-20s" % (player.get('summonerName'), player.get('role'), player.get('id')))
        print()
    return match

def get_player_details(player_id: str, match: Match):
    stats = [0, 0, 0, '']
    for game in match.games:
        for team in game.teams:
            for player in team.players:
                if player.id == player_id:
                    stats[0] += player.kills
                    stats[1] += player.deaths
                    stats[2] += player.assists
                    stats[3] = player.name
    print(stats[3])
    print("Kills | Deaths | Assists")
    print("%-5d | %-6d | %-7d" % (stats[0], stats[1], stats[2]))
    print("in %d games" % match.games.__len__())

# Print out all leagues and their id
def main():
    lolapi = RestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')
    params = {'hl': 'en-US'}
    leaguesList = lolapi.get('persisted/gw/getLeagues', ep_params=params).data.get('data').get('leagues')
    for league in leaguesList:
        print(league.get('name') + ' | ' + league.get('id'))
    league_name = input('Please enter League Name: ')
    league_id = ''
    for league in leaguesList:
        if(league.get('name') == league_name):
            league_id = league.get('id')
    get_all_matches(league_name, league_id)
    matchup = input('Please enter Matchup ID: ')
    match = get_matchup_details(matchup)
    player_id = input('Please enter Player ID: ')
    get_player_details(player_id, match)

if __name__ == '__main__':
    main()