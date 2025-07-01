# __init__.py
from datetime import datetime

from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_caching import Cache
from .celery_app import celery
import redis

# 1. Create extension instances globally, including Celery
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
cache = Cache()
# Configure login manager
login_manager.login_view = 'login'
redis_client = None

def create_app(config_class=Config):
    """The Application Factory."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions with the app object
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    cache.init_app(app)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    global redis_client
    redis_client = redis.from_url(app.config['CACHE_REDIS_URL'])

    with app.app_context():
        from . import routes, models

    @app.context_processor
    def inject_csrf_token():
        return dict(generate_csrf=generate_csrf)

    return app, celery

