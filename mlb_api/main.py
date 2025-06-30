import time
from datetime import datetime, timedelta

from mlb_api.rest_adapter import RestAdapter
from mlb_api.models import *

def main():
    # mlb_api = RestAdapter("statsapi.mlb.com")
    # event_schedule = mlb_api.get_schedule('2025-06-28', '2025-06-28')
    # matches = set()
    # for event in event_schedule.events:
    #     match = mlb_api.get_match(event.id)
    #     matches.add(match)
    #     print(match)
    #     print(match.home_team.id)
    # while True:
    #     print("---------------------------------------------------------------")
    #     for match in matches:
    #         if match.state != 'Final':
    #             print("updating match")
    #             mlb_api.update_match(match)
    #             print(match)
    #             time.sleep(1)
    #     time.sleep(15)
    today = datetime.today()
    tomorrow = today + timedelta(days=1)
    print(today.strftime("%Y-%m-%d"))
    print(tomorrow)


if __name__ == '__main__':
    main()