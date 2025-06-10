from app import app
from app import db
from seed import *
from app.scheduler import scheduler, schedule_initial_jobs
import atexit
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from app.tasks import *

app.logger.setLevel(logging.INFO)

def delete_alembic_version():
    try:
        with app.app_context():
            db.session.execute(db.text("DELETE FROM alembic_version"))
            db.session.commit()
        print("Alembic version information deleted successfully.")
    except Exception as e:
        print(f"An error occurred: {e}")

with app.app_context():
    # Will make seeding script separate
    #db.drop_all()
    #db.create_all()
    #seed_leagues()
    #seed_events()
    #seed_matches()
    app.config.from_object('app.scheduler.Config')
    scheduler.init_app(app)
    scheduler.start()
    schedule_initial_jobs(app)
    app.run(debug=True, use_reloader=False)
    scheduler.remove_all_jobs()
    atexit.register(lambda: scheduler.shutdown(wait=False))
