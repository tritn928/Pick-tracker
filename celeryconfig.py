# celeryconfig.py
import os
from celery.schedules import crontab

broker_url = os.environ.get('CELERY_BROKER_URL')
result_backend = os.environ.get('CELERY_BROKER_URL')
timezone = 'UTC'

imports = ('app.tasks',)
beat_schedule = {
    'update-leagues-every-hour': {
        'task': 'app.tasks.kick_off_league_update_workflow',
        'schedule': crontab(minute='0', hour='*'),
    },
    'process-unstarted-events-every-hour': {
        'task': 'app.tasks.process_unstarted_events',
        'schedule': crontab(minute='5', hour='*'),
    },
    'safety-check-for-live-games-every-30-minutes': {
        'task': 'app.tasks.check_in_progress',
        'schedule': crontab(minute='*/30'),
    },
    'cleanup_unused_match_players_once_a_day': {
        'task': 'app.tasks.cleanup_unused_match_players',
        'schedule': crontab(hour=0, minute=0),
    }
}