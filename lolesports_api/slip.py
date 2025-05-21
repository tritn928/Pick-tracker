from lolesports_api.models import Match
from typing import List

# Stores a player's kda in a map
class PlayerMapStats:
    def __init__(self, kills: int, deaths: int, assists: int):
        self.kills = kills
        self.deaths = deaths
        self.assists = assists

    def __add__(self, other):
        return PlayerMapStats(self.kills + other.kills, self.deaths + other.deaths, self.assists + other.assists)

# Slip class represents a parlay slip
# Contains a list of players to track
class Slip:
    # Contains the stats of a player throughout a match
    class ParlayPlayer:
        def __init__(self, name: str, id: str, current_match: Match, stats: List[PlayerMapStats], line: str = 0, num_maps: int = 0):
            self.current_match = current_match
            self.name = name
            self.id = id
            self.line = line
            self.num_maps = num_maps
            self.stats = stats

        def stats_for_game(self, game: int):
            return self.stats[game]

        def stats_for_all(self):
            ret = PlayerMapStats(0, 0, 0)
            for map_stat in self.stats:
                ret = ret + map_stat
            return ret

    def __init__(self, player: ParlayPlayer):
        self.players = []
        self.players.append(player)

    def add_player(self, player: ParlayPlayer):
        self.players.append(player)

    def update_player(self, player_id: str, match: Match):
        for i in range(len(self.players)):
            if self.players[i].id == player_id:
                self.players[i].current_match = match