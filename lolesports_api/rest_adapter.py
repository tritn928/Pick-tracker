import requests
import requests.packages

from lolesports_api.models import Result, Schedule, Match, Event
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
    def get_match(self, match_id: str) -> Match | None:
        params = {'hl': 'en-US', 'id': match_id}
        response = self.get('persisted/gw/getEventDetails', ep_params=params)
        if response.status_code != 200 or response.data.get('data').get('event') is None:
            print("Could not find match")
            return None
        match_details = Match(match_id, response.data)
        self.populate_games(match_details)
        return match_details

    # Runs once after creating a Match.
    # Fills in all Games that are completed or inProgress once
    def populate_games(self, match_details: Match):
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

        for game in match_details.games:
            if game.state == 'completed' or game.state == 'inProgress':
                full_url = game_url + game.game_id
                response = requests.get(url=full_url, headers=headers, params=params)
                if response.status_code == 204:
                    print("***************************GAME NOT FOUND**************************************")
                    break
                if response.status_code == 404:
                    print("***************************NO LIVE STATS****************************************")
                    break
                data_out = response.json()
                game.populate(data_out)



    def update_match(self, match_details: Match):
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

        game = match_details.get_active_game()
        if game is not None:
            print("updating game: " + str(game.number))
            full_url = game_url + game.game_id
            response = requests.get(url=full_url, headers=headers, params=params)
            if response.status_code == 204:
                print("*************************GAME NOT FOUND******************************")
                return
            if response.status_code == 404:
                print("***************************NO LIVE STATS****************************************")
                return
            game.update_from_frame(response.json())
        match_details.update_state()

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

    def get_teams(self, team_ids:List) -> List[Dict]:
        params = {'hl': 'en-US', 'id': ",".join(map(str, team_ids))}
        response = self.get('persisted/gw/getTeams', ep_params=params)
        if response.status_code != 200:
            print("could not get teams")
        return response.data.get('data').get('teams')

    def update_match_state(self, match:Match):
        params = {'hl': 'en-US', 'id': match.match_id}
        response = self.get('persisted/gw/getEventDetails', ep_params=params)
        if response.status_code != 200 or response.data.get('data').get('event') is None:
            print("Could not find match")
            return
        data = response.data.get('data').get('event').get('match')
        if data['games'][-1]['state'] == 'completed' or data['games'][-1]['state'] == 'unneeded' or data['games'][-1]['state'] == 'finished':
            match.state = 'completed'
