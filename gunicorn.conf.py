# Gunicorn config variables
loglevel = "info"
workers = 1  # Using 1 worker is crucial for low-memory environments like the free tier
threads = 2  # Each worker can handle multiple requests concurrently
bind = "0.0.0.0:5000"
keepalive = 120
timeout = 120