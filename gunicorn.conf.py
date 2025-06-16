# Gunicorn config variables
loglevel = "info"
workers = 2
bind = "0.0.0.0:5000"
keepalive = 120
timeout = 120