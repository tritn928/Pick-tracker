from typing import List, Dict


# Stores the result of any API call
class Result:
    def __init__(self, status_code: int, message: str = '', data: List[Dict] = None):
        self.status_code = int(status_code)
        self.message = str(message)
        self.data = data if data else []

# Wrapper around a League of Legends e-sport match
class Match:
    # A match has some number of games depending on the format, bo1, bo2, bo3, bo5
    class Game:
        # A game consists of two teams, blue and red
        class Team:
            # A team consists of 5 players
            class Player:
                # A player consists of their id, name, and relevant information from the game
                def __init__(self, p_id: int, id: str, name: str, champion: str, role: str):
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

                def update(self, data: Dict):
                    self.gold = data.get('totalGold')
                    self.level = data.get('level')
                    self.kills = data.get('kills')
                    self.deaths = data.get('deaths')
                    self.assists = data.get('assists')
                    self.creeps = data.get('creepScore')

                def __add__(self, other):
                    if isinstance(other, Match.Game.Team.Player):
                        added = Match.Game.Team.Player(self.p_id, self.id, self.name, self.champion, self.role)
                        added.kills += self.kills + other.kills
                        added.deaths += self.deaths + other.deaths
                        added.assists += self.assists + other.assists
                        return added
                    else:
                        return None

                def __str__(self) -> str:
                    return "%-25s | %-7s | %-15s | %-5d | %-5d | %-5d | %-6d | %-7d | %-6d " % (self.name, self.role,
                                                                                                self.champion,
                                                                                                self.level, self.gold,
                                                                                                self.kills, self.deaths,
                                                                                                self.assists,
                                                                                                self.creeps)

            # Constructor for a team. A team_id and participant data is passed in
            def __init__(self, team_id: str, data: List[Dict] = None):
                self.team_id = team_id
                self.players = []
                for participant in data:
                    self.players.append(
                        self.Player(participant.get('participantId'), participant.get('esportsPlayerId'),
                                    participant.get('summonerName'), participant.get('championId'),
                                    participant.get('role')))

            # Interprets the participant_id and updates the corresponding player
            def update_players(self, data: List[Dict]):
                for participant in data:
                    p_id = participant.get('participantId')
                    if p_id > 5:
                        p_id = p_id - 5
                    self.players[p_id - 1].update(participant)

        # Constructor for a Game. Passed in two teams
        def __init__(self, id: str, state: str, team_one: Team, team_two: Team):
            self.id = id
            self.state = state
            self.team_one = team_one
            self.team_two = team_two
            self.teams = []
            self.teams.append(self.team_one)
            self.teams.append(self.team_two)

    # Constructor for a Match, passed in a match_id and the result of a call to get_match
    def __init__(self, match_id: str, data: Dict = None):
        self.match_id = match_id
        self.games = []
        self.game_ids = []
        self.team_ids = []
        self.state = ''
        data = data.get('data').get('event').get('match')
        self.update_state(data)
        self.team_ids.append(data.get('teams')[0].get('id'))
        self.team_ids.append(data.get('teams')[1].get('id'))
        # only add games completed or in progress, others have no valid api call
        for game in data.get('games'):
            if game.get('state') == 'completed':
                self.game_ids.append(game.get('id'))
            if game.get('state') == 'inProgress':
                self.game_ids.append(game.get('id'))
        self.completed_game_ids = []

    def update_state(self, data: Dict):
        if data.get('games')[0].get('state') == 'unstarted':
            self.state = 'unstarted'
        elif data.get('games')[-1].get('state') == 'completed' or data.get('games')[-1].get('state') == 'unneeded':
            self.state = 'completed'
        else:
            self.state = 'inProgress'

    # Creates a Game object given the result of a call to get_game
    def add_game(self, game_id: str, data: Dict = None):
        update = True
        for game in self.games:
            if game.id == game_id and game.state == 'finished':
                update = False
                self.completed_game_ids.append(game_id)
                break
        if update:
            self.games.append(self.Game(
                data.get('esportsGameId'),
                data.get('frames')[-1].get('gameState'),
                self.Game.Team(data.get('gameMetadata').get('blueTeamMetadata').get('esportsTeamId'),
                               data.get('gameMetadata').get('blueTeamMetadata').get('participantMetadata')),
                self.Game.Team(data.get('gameMetadata').get('redTeamMetadata').get('esportsTeamId'),
                               data.get('gameMetadata').get('redTeamMetadata').get('participantMetadata'))))
        self.update_game(data)

    # Updates a Game object with the result of a call to get_game
    def update_game(self, data: Dict):
        self.games[-1].team_one.update_players(data.get('frames')[-1].get('blueTeam').get('participants'))
        self.games[-1].team_two.update_players(data.get('frames')[-1].get('redTeam').get('participants'))

# Creates a schedule consisting of league of legend events
class Schedule:
    # Structures an event into basic variables
    class Event:
        def __init__(self, start_time: str, state: str, match_id: str, strategy: int, teams: List[Dict] = None):
            self.start_time = start_time
            self.state = state
            self.match_id = match_id
            self.teams = teams if teams else []
            self.strategy = strategy
            self.match = None

        def __str__(self):
            if self.state == 'completed' or self.state == 'inProgress':
                return f"{self.start_time} | {self.state} | {self.match_id} | {self.teams[0].get('name')} vs {self.teams[1].get('name')} | {str(self.teams[0].get('result').get('gameWins'))} - {str(self.teams[1].get('result').get('gameWins'))}"
            elif self.state == 'unstarted':
                return f"{self.start_time} | {self.state} | {self.match_id} | {self.teams[0].get('name')} vs {self.teams[1].get('name')}"
            return ''

        def set_match(self, match: Match):
            self.match = match

    # Create a schedule by giving a league name, id, and the json result of the API call to get_schedule
    def __init__(self, league_name: str, league_id: str, data: List[Dict] = None):
        self.league_name = league_name
        self.league_id = league_id
        self.events = []
        for event in data:
            # Initialize an event and add to a List of events
            if event.get('type') == 'show':
                continue
            self.events.append(self.Event(event.get('startTime'), event.get('state'), event.get('match').get('id'),
                                          event.get('match').get('strategy').get('count'),
                                          event.get('match').get('teams')))

    def __str__(self):
        ret = ''
        for event in self.events:
            ret += event.__str__() + '\n'
        return ret