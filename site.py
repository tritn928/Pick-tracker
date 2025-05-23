from app import app
from app import db
from seed import seed_leagues
from app.scheduler import scheduler

with app.app_context():
    try:
        #db.drop_all()
        #db.create_all()
        #seed_leagues()
        scheduler.start()
        app.run(debug=True)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()