from app import app
from app import db
from seed import seed_leagues
from app.scheduler import scheduler
import atexit
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

def delete_alembic_version():
    try:
        with app.app_context():
            db.session.execute(db.text("DELETE FROM alembic_version"))
            db.session.commit()
        print("Alembic version information deleted successfully.")
    except Exception as e:
        print(f"An error occurred: {e}")

with app.app_context():
    #db.drop_all()
    #db.create_all()
    #seed_leagues()
    scheduler.start()
    app.run(debug=True, use_reloader=False)
    atexit.register(lambda: scheduler.shutdown(wait=False))
