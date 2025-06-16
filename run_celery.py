# run_celery.py

from app import create_app, celery

# By calling create_app() here, we ensure that the Celery app is configured
# and the ContextTask is set up before the worker starts.
# This is the crucial step that the `celery` command was not doing on its own.
app = create_app()