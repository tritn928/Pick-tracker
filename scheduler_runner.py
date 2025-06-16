import time
from wsgi import app
#from app.scheduler import schedule_initial_jobs
from flask_apscheduler import APScheduler

print("Starting scheduler runner script...")

# Create a Flask app instance to provide context for the scheduler
# = create_app()
# Manually push the context to make it available for the setup
app.app_context().push()
scheduler = APScheduler()
# Initialize the scheduler extension with the app
scheduler.init_app(app)

# Add the defined jobs to the scheduler queue
#schedule_initial_jobs()
scheduler.add_job(
        id='job_heartbeat',
        func='app.tasks2:heartbeat',
        trigger='interval',
        seconds=30,
        replace_existing=True
    )
app.logger.info("Scheduled: Heartbeat job (every 30 seconds).")

# Print all jobs to confirm they were scheduled correctly
print("\n--- Current Jobs in Scheduler ---")
for job in scheduler.get_jobs():
    print(job)
print("---------------------------------\n")

# Start the scheduler's background process
scheduler.start()
print("Scheduler started. Running in background...")

# Keep this main script alive so the scheduler's background thread can run
try:
    while True:
        time.sleep(1)
except (KeyboardInterrupt, SystemExit):
    # Shut down the scheduler cleanly on exit
    scheduler.shutdown()
