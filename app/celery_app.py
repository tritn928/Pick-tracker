# app/celery_app.py

from celery import Celery

# Give your app a name. It's good practice to use the package name.
celery = Celery('app')

# Load all configuration from the dedicated celeryconfig.py file.
celery.config_from_object('celeryconfig')