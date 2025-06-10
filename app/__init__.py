from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_caching import Cache

csrf = CSRFProtect()
login_manager = LoginManager()
cache = Cache()
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'
app = Flask(__name__)
app.config.from_object(Config)
login_manager.init_app(app)
csrf.init_app(app)
cache.init_app(app)

@app.context_processor
def inject_csrf_token():
    return dict(generate_csrf=generate_csrf)

db = SQLAlchemy(app)
migrate = Migrate(app, db)

from app import routes, models