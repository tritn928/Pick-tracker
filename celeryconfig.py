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
    'check-events-every-hour': {
        'task': 'app.tasks.check_and_start_polling',
        'schedule': crontab(minute='5', hour='*'),
    },
    'cleanup_unused_match_players_once_a_day': {
        'task': 'app.tasks.cleanup_unused_match_players',
        'schedule': crontab(hour=0, minute=0),
    }
}