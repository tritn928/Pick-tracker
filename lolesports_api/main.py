from lolesports_api.rest_adapter import RestAdapter

# get all games on the front page of lolesports.com
# display score if completed
# else displays the upcoming matchup

# api_key from documentation
lolapi = RestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')
eventSchedule = lolapi.get_schedule('lck', '98767991310872058')
for event in eventSchedule.events:
    # if completed, print out details
    if event.state == 'completed':
        print(event.start_time + ' | ' + event.state + ' | ' + event.match_id + ' | ' + event.teams[0].get('name') + ' vs ' + event.teams[1].get('name')
              + ' | ' + str(event.teams[0].get('result').get('gameWins')) + "-" +
              str(event.teams[1].get('result').get('gameWins')))
        matchDetails = lolapi.get_match(event.match_id)
        # Then loop over all of the games, displaying the stats of each player
        index = 0
        while index < len(matchDetails.games):
            print("********************************GAME %d**************************************" % (index + 1))
            print("Player Name               | Role    | Champion        | Level | Gold  | Kills | Deaths | Assists | Creeps ")
            for player in matchDetails.games[index].team_one.players:
                print(player)
            print("-----------------------------------------------------------------------------")
            for player in matchDetails.games[index].team_two.players:
                print(player)
            index += 1
    # else just print the matchup
    if event.state == 'unstarted':
        print(event.start_time + ' | ' + event.state + ' | ' + event.match_id + ' | ' + event.teams[0].get(
            'name') + ' vs ' + event.teams[1].get('name')
              + ' | ' + "Best of " + str(event.strategy))
