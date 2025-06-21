# celeryconfig.py
import os
from celery.schedules import crontab

broker_url = os.environ.get('CELERY_BROKER_URL')
result_backend = os.environ.get('CELERY_BROKER_URL')
timezone = 'UTC'
task_always_eager = False

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
    'safety-check-for-live-games-every-30-minutes': {
        'task': 'app.tasks.check_in_progress',
        'schedule': crontab(minute='*/30'), # Run every 30 minutes
    },
    'cleanup_unused_match_players_once_a_day': {
        'task': 'app.tasks.cleanup_unused_match_players',
        'schedule': crontab(hour=0, minute=0),
    }
}