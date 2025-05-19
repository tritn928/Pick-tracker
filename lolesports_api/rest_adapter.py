import requests
import requests.packages
from lolesports_api.models import Result, Schedule, Match
from typing import List, Dict
from datetime import datetime, timedelta

# Wrapper around the unofficial lolesport-sapi
class RestAdapter:
    def __init__(self, hostname: str, api_key: str = ''):
        self.url = "https://{}/".format(hostname)
        self._api_key = api_key

    # Generic GET call
    def get(self, endpoint: str, ep_params: Dict = None) -> Result:
        full_url = self.url + endpoint
        headers = {'x-api-key': self._api_key}
        response = requests.get(url=full_url, headers=headers, params = ep_params)
        data_out = response.json()
        return Result(response.status_code, message=response.reason, data=data_out)

    # A wrapper around a call to getSchedule, returning a Schedule object
    def get_schedule(self, league_name: str, league_id: str) -> Schedule:
        headers = {'x-api-key': self._api_key}
        params = {'hl': 'en-US', 'leagueId': league_id}
        full_url = self.url + 'persisted/gw/getSchedule'
        response = requests.get(url=full_url, headers=headers, params = params)
        data_out = response.json()
        return Schedule(league_name, league_id, data_out.get('data').get('schedule').get('events'))

    # Wrapper around the getEventDetails and live window calls
    # Given a match_id, creates a Match object
    # Retrieves the appropriate game_ids for the match and updates the Match object with live or completed stats
    def get_match(self, match_id: str) -> Match:
        headers = {'x-api-key': self._api_key}
        params = {'hl': 'en-US', 'id': match_id}
        full_url = self.url + 'persisted/gw/getEventDetails'
        response = requests.get(url=full_url, headers=headers, params=params)
        data_out = response.json()
        match_details = Match(match_id, data_out)
        return self.update_match(match_details)

    def update_match(self, match_details: Match) -> Match:
        headers = {'x-api-key': self._api_key}
        game_url = 'https://feed.lolesports.com/livestats/v1/window/'

        # Get current time and convert conform to fit api standard
        currentTime = datetime.now()
        seconds = (currentTime.replace(tzinfo=None) - currentTime.min).seconds
        roundTo = 60
        rounding = (seconds + roundTo / 2) // roundTo * roundTo
        currentTime = currentTime + timedelta(0, rounding - seconds, -currentTime.microsecond)
        params = {'startingTime': currentTime.strftime("%Y-%m-%dT%H:%M:%SZ")}

        # Update match with game details
        for game_id in match_details.game_ids:
            full_url = game_url + game_id
            response = requests.get(url=full_url, headers=headers, params=params)
            if response.status_code == 204:
                print("***************************GAME NOT FOUND**************************************")
                break
            data_out = response.json()
            match_details.add_game(data_out)
        return match_details
