from datetime import timedelta

from app import app
from app import db
from app.models import *
from flask_apscheduler import APScheduler
import time

# 1. Initialize the scheduler
scheduler = APScheduler()

class Config:
    SCHEDULER_API_ENABLED = True
    SCHEDULER_JOBSTORES = {
        'default': {'type': 'sqlalchemy', 'url': 'sqlite:///app.db'} # Use your main DB URL here
    }
    SCHEDULER_EXECUTORS = {
        'default': {'type': 'threadpool', 'max_workers': 20}
    }

def schedule_initial_jobs(app):
    with app.app_context():
        # Using add_job with replace_existing=True is safe for restarts

        # Job 1: Check for new events every hour
        scheduler.add_job(
            id='job_update_leagues',
            func='app.tasks:update_leagues',  # Path to your function
            trigger='interval',
            hours=1,
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(hours=1)
        )

        # Job 2: Check for upcoming matches every 5 minutes
        scheduler.add_job(
            id='job_update_unstarted_events',
            func='app.tasks:update_unstarted_events',  # Path to your function
            trigger='interval',
            minutes=5,
            replace_existing=True,
            next_run_time=datetime.now()
        )

        scheduler.add_job(
            id='print_jobs',
            func='app.tasks:print_jobs',
            trigger='interval',
            minutes=1,
            replace_existing=True,
            next_run_time=datetime.now()
        )