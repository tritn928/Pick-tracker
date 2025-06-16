from scheduler_runner import scheduler
from flask import current_app

def schedule_initial_jobs():
    """
    Adds the application's recurring jobs to the scheduler.
    'replace_existing=True' prevents duplicate jobs if the scheduler restarts.
    """
    scheduler.add_job(
        id='job_heartbeat',
        func='app.tasks2:heartbeat',
        trigger='interval',
        seconds=30,
        replace_existing=True
    )
    current_app.logger.info("Scheduled: Heartbeat job (every 30 seconds).")