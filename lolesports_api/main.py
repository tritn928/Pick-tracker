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
    print(event_schedule)
    matches = set()

    matches.add(lolapi.get_match('113470922764572294'))
    while True:
        for match in matches:
            game = match.get_active_game()
            if game:
                print(f"Game {game.number} - {game.state}")
                if game.participants:
                    for p in game.participants:
                        participant = game.participants[p]
                        print(f"{participant.name} : {participant.kills}/{participant.deaths}/{participant.assists}")
            if game is None:
                print("no active games")
                return
            lolapi.update_match(match)
            match.update_state()

        time.sleep(15)


if __name__ == '__main__':
    main()