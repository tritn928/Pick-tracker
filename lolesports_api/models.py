from typing import List, Dict

# Stores the result of any API call
class Result:
    def __init__(self, status_code: int, message: str = '', data: List[Dict] = None):
        self.status_code = int(status_code)
        self.message = str(message)
        self.data = data if data else []

# Structures an event into basic variables
class Event:
    def __init__(self, start_time: str, state: str, match_id: str, strategy: int, teams: List[Dict] = None):
        self.start_time = start_time
        self.state = state
        self.match_id = match_id
        self.teams = teams if teams else []
        self.strategy = strategy

    def __str__(self):
        if self.state == 'completed' or self.state == 'inProgress':
            return f"{self.start_time} | {self.state} | {self.match_id} | {self.teams[0].get('name')} vs {self.teams[1].get('name')} | {str(self.teams[0].get('result').get('gameWins'))} - {str(self.teams[1].get('result').get('gameWins'))}"
        elif self.state == 'unstarted':
            return f"{self.start_time} | {self.state} | {self.match_id} | {self.teams[0].get('name')} vs {self.teams[1].get('name')}"
        return ''

# Creates a schedule consisting of league of legend events
class Schedule:
    # Create a schedule by giving a league name, id, and the json result of the API call to get_schedule
    def __init__(self, league_name: str, league_id: str, data: List[Dict] = None):
        self.league_name = league_name
        self.league_id = league_id
        self.events = []
        for event in data:
            if event.get('type') == 'show':
                continue
            self.events.append(Event(event.get('startTime'), event.get('state'), event.get('match').get('id'),
                                          event.get('match').get('strategy').get('count'),
                                          event.get('match').get('teams')))

    def __str__(self):
        ret = ''
        for event in self.events:
            ret += event.__str__() + '\n'
        return ret

class Game:
    class PlayerStats:
        def __init__(self, p_id:int, id: str, name: str, champion: str, role: str):
            self.p_id = p_id
            self.id = id
            self.name = name
            self.champion = champion
            self.role = role
            self.gold = 0
            self.level = 0
            self.kills = 0
            self.deaths = 0
            self.assists = 0
            self.creeps = 0

        def update(self, stats):
            self.gold = stats['totalGold']
            self.level = stats['level']
            self.kills = stats['kills']
            self.deaths = stats['deaths']
            self.assists = stats['assists']
            self.creeps = stats['creepScore']

    class TeamStats:
        def __init__(self, id, totalGold, inhibitors, towers, barons, totalKills):
            self.id = id
            self.totalGold = totalGold
            self.inhibitors = inhibitors
            self.towers = towers
            self.barons = barons
            self.totalKills = totalKills

    def __init__(self, game_id: str, state: str, number:int):
        self.game_id = game_id
        self.state = state
        self.number = number
        self.blue_team = None
        self.red_team = None
        self.participants = {}

    def populate(self, data):
        self.blue_team = self.TeamStats(id=data['gameMetadata']['blueTeamMetadata']['esportsTeamId'],
                                        totalGold=data['frames'][-1]['blueTeam']['totalGold'],
                                        inhibitors=data['frames'][-1]['blueTeam']['inhibitors'],
                                        towers=data['frames'][-1]['blueTeam']['towers'],
                                        barons=data['frames'][-1]['blueTeam']['barons'],
                                        totalKills=data['frames'][-1]['blueTeam']['totalKills'])
        self.red_team = self.TeamStats(id=data['gameMetadata']['redTeamMetadata']['esportsTeamId'],
                                        totalGold=data['frames'][-1]['redTeam']['totalGold'],
                                        inhibitors=data['frames'][-1]['redTeam']['inhibitors'],
                                        towers=data['frames'][-1]['redTeam']['towers'],
                                        barons=data['frames'][-1]['redTeam']['barons'],
                                        totalKills=data['frames'][-1]['redTeam']['totalKills'])
        for i in range(0, 5):
            self.participants[i+1] = self.PlayerStats(p_id=i+1,
                                                    id=data['gameMetadata']['blueTeamMetadata']['participantMetadata'][i]['esportsPlayerId'],
                                                    name=data['gameMetadata']['blueTeamMetadata']['participantMetadata'][i]['summonerName'],
                                                    champion=data['gameMetadata']['blueTeamMetadata']['participantMetadata'][i]['championId'],
                                                    role=data['gameMetadata']['blueTeamMetadata']['participantMetadata'][i]['role'])

        for i in range(0, 5):
            self.participants[i+6] = self.PlayerStats(p_id=i+6,
                                                    id=data['gameMetadata']['redTeamMetadata']['participantMetadata'][i-1]['esportsPlayerId'],
                                                    name=data['gameMetadata']['redTeamMetadata']['participantMetadata'][i-1]['summonerName'],
                                                    champion=data['gameMetadata']['redTeamMetadata']['participantMetadata'][i-1]['championId'],
                                                    role=data['gameMetadata']['redTeamMetadata']['participantMetadata'][i-1]['role'])
        self.update_from_frame(data['frames'][-1])

    def update_from_frame(self, frame):
        self.blue_team.totalGold = frame['blueTeam']['totalGold']
        self.blue_team.inhibitors = frame['blueTeam']['inhibitors']
        self.blue_team.towers = frame['blueTeam']['towers']
        self.blue_team.barons = frame['blueTeam']['barons']
        self.blue_team.totalKills = frame['blueTeam']['totalKills']
        for i in range(0,5):
            self.participants[i+1].update(frame['blueTeam']['participants'][i])

        self.red_team.totalGold = frame['redTeam']['totalGold']
        self.red_team.inhibitors = frame['redTeam']['inhibitors']
        self.red_team.towers = frame['redTeam']['towers']
        self.red_team.barons = frame['redTeam']['barons']
        self.red_team.totalKills = frame['redTeam']['totalKills']
        for i in range(0,5):
            self.participants[i+6].update(frame['redTeam']['participants'][i])

        if frame['gameState'] == 'finished':
            self.state = 'completed'




class Match:
    # Constructor for a Match, passed in a match_id and the result of a call to get_match
    def __init__(self, match_id: str, data: Dict = None):
        self.match_id = match_id
        self.games = []
        self.game_ids = []
        self.team_ids = []
        self.state = ''
        data = data.get('data').get('event').get('match')
        self.team_ids.append(data.get('teams')[0].get('id'))
        self.team_ids.append(data.get('teams')[1].get('id'))
        self.create_games(data.get('games'))
        self.update_state()

    def update_state(self):
        if self.games[0].state == 'unstarted':
            self.state = 'unstarted'
        elif self.games[-1].state == 'completed' or self.games[-1].state == 'unneeded':
            self.state = 'completed'
        else:
            self.state = 'inProgress'

    def create_games(self, data):
        for game in data:
            self.games.append(Game(game_id=game.get('id'), state=game.get('state'), number=game.get('number')))

    def get_active_game(self):
        for game in self.games:
            if game.state == 'inProgress' or game.state == 'unstarted':
                return game
        return None
