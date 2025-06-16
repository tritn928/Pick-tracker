import os


class Config:
    # --- Flask Core and Extensions Configuration ---
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'a-very-secret-key'

    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Caching Configuration ---
    CACHE_TYPE = 'RedisCache'
    CACHE_REDIS_URL = os.environ.get('CACHE_REDIS_URL')
    CACHE_DEFAULT_TIMEOUT = 300