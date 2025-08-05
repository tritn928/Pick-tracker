import time
from datetime import datetime, timedelta

from mlb_api.rest_adapter import RestAdapter
from mlb_api.models import *

def main():
    mlb_api = RestAdapter("statsapi.mlb.com")
    today = datetime.today() - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    event_schedule = mlb_api.get_schedule(today.strftime("%Y-%m-%d"),tomorrow.strftime("%Y-%m-%d"))
    print(event_schedule)
    match = mlb_api.get_match(777199)
    for id, player in match.home_team.players.items():
        if player.position != 'Pitcher':
            print(player.position)
            print(player.batting_stats)
        else:
            print(player.position)
            print(player.pitching_stats)
if __name__ == '__main__':
    main()