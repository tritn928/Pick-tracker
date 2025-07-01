import time
from datetime import datetime, timedelta

from mlb_api.rest_adapter import RestAdapter
from mlb_api.models import *

def main():
    mlb_api = RestAdapter("statsapi.mlb.com")
    today = datetime.today() + timedelta(days=3)
    tomorrow = today + timedelta(days=1)
    event_schedule = mlb_api.get_schedule(today.strftime("%Y-%m-%d"),tomorrow.strftime("%Y-%m-%d"))
    print(event_schedule)
    match = mlb_api.get_match(777295)
    print(match.to_dict())


if __name__ == '__main__':
    main()