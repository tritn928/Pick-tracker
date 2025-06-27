from typing import List, Dict


# Stores the result of any API call
class Result:
    def __init__(self, status_code: int, message: str = '', data: Dict = None):
        self.status_code = int(status_code)
        self.message = str(message)
        self.data = data if data else []

class Event:
    def __init__(self, id: int, endpoint: str, start_time: str, state: str, teams: Dict = None):
        self.id = id
        self.endpoint = endpoint
        self.start_time = start_time
        self.state = state
        self.teams = teams if teams else []
        self.home_id = teams['home']['team']['id']
        self.home_name = teams['home']['team']['name']
        self.away_name = teams['away']['team']['name']
        self.away_id = teams['away']['team']['id']

    def update(self, data: Dict):
        data = data['dates'][0]['games'][0]
        self.state = data['status']['abstractGameState']
        # Can add a winner later

    def __str__(self):
        return f"{self.home_name}({self.home_id}) vs {self.away_name}({self.away_id}) at {self.start_time}, pk: {self.id}, state: {self.state}, link: {self.endpoint}"

# Creates a Schedule consisting of MLB Events
class Schedule:
    def __init__(self, start_date: str, end_date:str, data: Dict = None):
        self.start_date = start_date
        self.end_date = end_date
        self.num_games = data['totalGames']
        self.events = []
        for date in data['dates']:
            for game in date['games']:
                self.events.append(Event(
                    game['gamePk'],
                    game['link'],
                    game['gameDate'],
                    game['status']['abstractGameState'],
                    game['teams']
                ))

    def __str__(self):
        ret = ''
        for event in self.events:
            ret += event.__str__() + '\n'
        return ret

class Match:
    class Team:
        class Boxscore:
            def __init__(self, id: int, name: str, position:str, battingOrder:str, batting_stats:Dict, pitching_stats:Dict, gameStatus:Dict):
                self.id = id
                self.name = name
                self.position = position
                self.battingOrder = battingOrder
                self.batting_stats = batting_stats
                self.pitching_stats = pitching_stats
                self.gameStatus = gameStatus
                if 'summary' in self.batting_stats:
                    self.summary = self.batting_stats['summary']
                else:
                    self.summary = self.pitching_stats['summary']

            def update(self, player_data:Dict):
                self.battingOrder = player_data.get('battingOrder', 0)
                self.batting_stats = player_data['stats']['batting']
                self.pitching_stats = player_data['stats']['pitching']
                self.gameStatus = player_data['gameStatus']
                if 'summary' in self.batting_stats:
                    self.summary = self.batting_stats['summary']
                else:
                    self.summary = self.pitching_stats['summary']

            def __str__(self):
                if 'summary' in self.batting_stats:
                    return "%30s | %-30s" % (self.name, self.batting_stats['summary'])
                else:
                    return "%30s | %30s" % (self.name, self.pitching_stats['summary'])

        def __init__(self, name:str, id:int, boxscore_data:Dict):
            self.name = name
            self.id = id
            self.players = {}
            for player in boxscore_data['players']:
                player_data = boxscore_data['players'][player]
                if 'summary' in player_data['stats']['batting'] or 'summary' in player_data['stats']['pitching']:
                    self.players[player_data['person']['id']] = (
                        self.Boxscore(
                        player_data['person']['id'],
                        player_data['person']['fullName'],
                        player_data['position']['name'],
                        player_data.get('battingOrder', 0),
                        player_data['stats']['batting'],
                        player_data['stats']['pitching'],
                        player_data['gameStatus']
                    ))

        def update_players(self, boxscore_data:Dict):
            for player in boxscore_data['players']:
                player_data = boxscore_data['players'][player]
                if 'summary' in player_data['stats']['batting'] or 'summary' in player_data['stats']['pitching']:
                    player = self.players.get(player_data['person']['id'])
                    if player is None:
                        self.players[player_data['person']['id']] = (
                            self.Boxscore(
                                player_data['person']['id'],
                                player_data['person']['fullName'],
                                player_data['position']['name'],
                                player_data.get('battingOrder', 0),
                                player_data['stats']['batting'],
                                player_data['stats']['pitching'],
                                player_data['gameStatus']
                            ))
                    else:
                        self.players.get(player_data['person']['id']).update(player_data)

    def __init__(self, match_id: int, event:Event, boxscore: Dict):
        self.id = match_id
        self.home_team = self.Team(boxscore['home']['team']['name'], boxscore['home']['team']['id'], boxscore['home'])
        self.away_team = self.Team(boxscore['away']['team']['name'], boxscore['away']['team']['id'], boxscore['away'])
        self.event = event

    def update_from_boxscore(self, boxscore:Dict):
        self.home_team.update_players(boxscore['home'])
        self.away_team.update_players(boxscore['away'])

    def __str__(self):
        ret = f"{self.home_team.name} vs {self.away_team.name}\n"
        ret += f"-----------------HOME--------------------\n"
        for player in self.home_team.players:
            ret += str(self.home_team.players[player]) + '\n'
        ret += f"-----------------AWAY--------------------\n"
        for player in self.away_team.players:
            ret += str(self.away_team.players[player]) + '\n'
        return ret
