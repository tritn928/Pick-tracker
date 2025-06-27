import time
from mlb_api.rest_adapter import RestAdapter
from mlb_api.models import *

def main():
    mlb_api = RestAdapter("statsapi.mlb.com")
    event_schedule = mlb_api.get_schedule('2025-06-26', '2025-06-26')
    matches = set()
    for event in event_schedule.events:
        match = mlb_api.get_match(event.id, event)
        matches.add(match)
        print(match)
    while True:
        print("---------------------------------------------------------------")
        for match in matches:
            if match.event.state != 'Final':
                print("updating match")
                mlb_api.update_match(match)
                print(match)
                time.sleep(.5)
            mlb_api.update_event(match.event)
        time.sleep(10)


if __name__ == '__main__':
    main()