from lolesports_api.rest_adapter import RestAdapter
from lolesports_api.models import Match, Schedule
from lolesports_api.slip import Slip, PlayerMapStats
from typing import List, Dict, Any
import time
from datetime import datetime, timedelta

def main():
    lolapi = RestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')
    leaguesList = lolapi.get_leagues()
    event_schedule = lolapi.get_schedule(league_name='MSI', league_id='98767991325878492')
    match = lolapi.get_match('113470922764572270')
    while True:
        game = match.get_active_game()
        if game:
            print(game.number)
            print(game.state)
            if game.participants:
                for p in game.participants:
                    participant = game.participants[p]
                    print(f"{participant.name} ({p})({participant.id}): {participant.kills}/{participant.deaths}/{participant.assists}")
        lolapi.update_match(match)
        time.sleep(10)
        if match.state == 'completed':
            return


if __name__ == '__main__':
    main()