# celeryconfig.py

from celery.schedules import crontab

# Basic broker and backend configuration
broker_url = 'redis://redis:6379/1'
result_backend = 'redis://redis:6379/2'
timezone = 'UTC'

# --- THE MOST IMPORTANT LINE ---
# This tuple explicitly tells Celery which modules contain your tasks.
imports = ('app.tasks',)
beat_schedule = {
    'update-leagues-every-hour': {
        'task': 'app.tasks.kick_off_league_update_workflow',
        'schedule': crontab(minute='0', hour='*'),
    },
    'process-unstarted-events-every-5-minutes': {
        'task': 'app.tasks.process_unstarted_events',
        'schedule': crontab(minute='*/5'), # Run every 5 minutes
    },
    'safety-check-for-live-games-every-20-minutes': {
        'task': 'app.tasks.check_in_progress',
        'schedule': crontab(minute='*/20'), # Run every 20 minutes
    }
}