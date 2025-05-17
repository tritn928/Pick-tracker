import requests
import requests.packages
from lolesports_api.rest_adapter import RestAdapter
from datetime import datetime, timedelta, timezone
from lolesports_api.models import Match
import time
# get all live games
# create a match for each
# update matches every minute

full_url = 'https://esports-api.lolesports.com/persisted/gw/getEventDetails'
headers = {'x-api-key': '0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z'}
params = {'hl': 'en-US', 'id': '113503303285384345'}
response = requests.get(url=full_url, headers=headers, params = params)
data_out = response.json()
match = Match('113503303285384345', data_out.get('data').get('event').get('match'))
game_url = 'https://feed.lolesports.com/livestats/v1/window/'
game_id = '113503303285384347'
currentTime = datetime.now(timezone.utc)
seconds = (currentTime.replace(tzinfo=None) - currentTime.min).seconds
roundTo = 10
rounding = (seconds + roundTo / 2) // roundTo * roundTo
currentTime = currentTime + timedelta(0, rounding - seconds, -currentTime.microsecond)
currentTime = currentTime - timedelta(minutes=1)
params = {'startingTime': currentTime.strftime("%Y-%m-%dT%H:%M:%SZ")}
full_url = game_url + game_id
response = requests.get(url=full_url, headers=headers, params=params)
data_out = response.json()
match.add_game(data_out)

while(True):
    currentTime = datetime.now(timezone.utc)
    seconds = (currentTime.replace(tzinfo=None) - currentTime.min).seconds
    roundTo = 10
    rounding = (seconds + roundTo / 2) // roundTo * roundTo
    currentTime = currentTime + timedelta(0, rounding - seconds, -currentTime.microsecond)
    currentTime = currentTime - timedelta(seconds=30)
    response = requests.get(url=full_url, headers=headers, params=params)
    data_out = response.json()
    match.update_game(data_out)
    params = {'startingTime': currentTime.strftime("%Y-%m-%dT%H:%M:%SZ")}
    print(currentTime)
    print("********************************GAME 1**************************************")
    print("Player Name               | Role    | Champion        | Level | Gold  | Kills | Deaths | Assists | Creeps ")
    for player in match.games[0].team_one.players:
        print(player)
    print("-----------------------------------------------------------------------------")
    for player in match.games[0].team_two.players:
        print(player)
    time.sleep(10)
    print("********************************UPDATE**************************************")