from app import db
from app import app
from lolesports_api.rest_adapter import RestAdapter
from app.models import League, Event

# ignore broken schedule calls
# ignore old leagues
ignore = ['LCL', 'TFT Esports', 'LCS', "King's Duel", 'Worlds Qualifying Series', 'LCO', 'LLA', 'CBLOL']

def seed_leagues():
    lolapi = RestAdapter(hostname='esports-api.lolesports.com', api_key='0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z')
    leaguesList = lolapi.get_leagues()
    for league in leaguesList:
        if league['name'] in ignore:
            continue
        to_add = League(league_name=league['name'], league_id=league['id'])
        db.session.add(to_add)
    db.session.commit()
    app.logger.debug("finished seeding leagues")