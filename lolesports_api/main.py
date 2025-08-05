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
    match = lolapi.get_match('113470922758018585')
    print(match.to_dict())


if __name__ == '__main__':
    main()