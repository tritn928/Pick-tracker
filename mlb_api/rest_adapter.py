import requests
import requests.packages
from typing import List, Dict

from app.models import Event
from mlb_api.models import *

class RestAdapter:
    def __init__(self, hostname: str):
        self.url = "https://{}".format(hostname)

    def get(self, endpoint: str, ep_params: Dict = None) -> Result:
        full_url = self.url + endpoint
        response = requests.get(url=full_url, params = ep_params)
        data_out = response.json()
        return Result(response.status_code, message=response.reason, data=data_out)

    def get_schedule(self, start: str, end: str):
        params = {'sportId': 1,
                  'usingPrivateEndpoint': False,
                  'startDate': start,
                  'endDate': end}
        r = self.get("/api/v1/schedule", ep_params=params)
        if r.status_code == 200:
            return Schedule(start, end, r.data)
        else:
            raise Exception(r.status_code)

    def get_team(self, team_id: int, date: str):
        params = {'date': date}
        r = self.get("/api/v1/teams/{}/roster/GAMEDAY".format(team_id), ep_params=params)
        if r.status_code == 200:
            return r.data['roster']
        else:
            raise Exception(r.status_code)

    def get_boxscore(self, match_id: int):
        r = self.get("/api/v1/game/{}/boxscore".format(match_id))
        if r.status_code == 200:
            return r.data['teams']
        else:
            raise Exception(r.status_code)

    def get_match(self, match_id: int, event:Event) -> Match:
        boxscore =    self.get_boxscore(match_id)
        return Match(match_id, event, boxscore)

    def update_match(self, match:Match):
        boxscore = self.get_boxscore(match.id)
        match.update_from_boxscore(boxscore)

    def update_event(self, event: Event):
        params = {'sportId': 1,
                  'usingPrivateEndpoint': False,
                  'gamePk': event.id
                  }
        r = self.get("/api/v1/schedule", ep_params=params)
        if r.status_code == 200:
            event.update(r.data)
        else:
            raise Exception(r.status_code)



