import requests
import requests.packages
from lolesports_api.models import Result, Schedule, Match
from typing import List, Dict
from datetime import datetime, timedelta, timezone

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
        params = {'hl': 'en-US', 'leagueId': league_id}
        response = self.get('persisted/gw/getSchedule', ep_params=params)
        if response.status_code != 200 or len(response.data.get('data').get('schedule').get('events')) == 0:
            print("Could not find league")
            exit(1)
        return Schedule(league_name, league_id, response.data.get('data').get('schedule').get('events'))

    # Wrapper around the getEventDetails and live window calls
    # Given a match_id, creates a Match object
    # Retrieves the appropriate game_ids for the match and updates the Match object with live or completed stats
    def get_match(self, match_id: str) -> Match:
        params = {'hl': 'en-US', 'id': match_id}
        response = self.get('persisted/gw/getEventDetails', ep_params=params)
        if response.status_code != 200 or response.data.get('data').get('event') is None:
            print("Could not find match")
            exit(1)
        match_details = Match(match_id, response.data)
        return self.update_match(match_details)

    def update_match(self, match_details: Match) -> Match:
        headers = {'x-api-key': self._api_key}
        game_url = 'https://feed.lolesports.com/livestats/v1/window/'

        # Get current time and convert conform to fit api standard
        currentTime = datetime.now(timezone.utc)
        seconds = (currentTime.replace(tzinfo=None) - currentTime.min).seconds
        roundTo = 10
        rounding = (seconds + roundTo / 2) // roundTo * roundTo
        currentTime = currentTime + timedelta(0, rounding - seconds, -currentTime.microsecond)
        currentTime = currentTime - timedelta(minutes=1)
        params = {'startingTime': currentTime.strftime("%Y-%m-%dT%H:%M:%SZ")}

        do = True
        # Update match with game details
        for game_id in match_details.game_ids:
            #TODO: find a way to tell if game_id is complete, then skip it if it is
            for completed_game_id in match_details.completed_game_ids:
                if game_id == completed_game_id:
                    do = False
            if do:
                full_url = game_url + game_id
                response = requests.get(url=full_url, headers=headers, params=params)
                if response.status_code == 204:
                    print("***************************GAME NOT FOUND**************************************")
                    break
                if response.status_code == 404:
                    print("***************************NO LIVE STATS****************************************")
                    break
                data_out = response.json()
                match_details.add_game(game_id, data_out)
        return match_details

    def get_live(self) -> Schedule:
        params = {'hl': 'en-US'}
        response = self.get('persisted/gw/getLive', ep_params=params)
        if response.status_code != 200 or len(response.data.get('data').get('schedule').get('events')) == 0:
            print("no live events")
        return Schedule('', '', response.data.get('data').get('schedule').get('events'))

    def get_leagues(self) -> List[Dict]:
        params = {'hl': 'en-US'}
        response = self.get('persisted/gw/getLeagues', ep_params=params)
        if response.status_code != 200:
            print("could not get leagues")
        return response.data.get('data').get('leagues')