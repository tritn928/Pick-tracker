from celery import group

from app import create_app
from app import db
import click
import logging
from app.models import *
from app.tasks import seed_leagues_task, seed_events_for_league_task, seed_match_for_event_task

app, celery = create_app()

app.logger.setLevel(logging.INFO)

# Creates all tables, seeds League of Legends
@app.cli.command("seed-db")
def seed_db_command():
    click.echo("Dropping and creating all tables...")
    db.drop_all()
    db.create_all()

    click.echo("Stage 1: Seeding leagues...")
    seed_leagues_task.delay().get(timeout=300)
    click.echo("Leagues seeded successfully.")

    click.echo("Stage 2: Queueing event seeding for all leagues...")
    league_ids = [league.id for league in League.query.with_entities(League.id).all()]
    event_seeding_group = group(seed_events_for_league_task.s(league_id) for league_id in league_ids)
    event_result = event_seeding_group.apply_async()
    event_result.get()
    click.echo("All events seeded successfully.")

    click.echo("Stage 3: Queueing match seeding for all events...")
    event_ids = [event.id for event in Event.query.with_entities(Event.id).all()]
    match_seeding_group = group(seed_match_for_event_task.s(event_id) for event_id in event_ids)
    match_result = match_seeding_group.apply_async()
    match_result.get()
    click.echo("All matches seeded successfully.")

    click.echo("✅ Database has been seeded.")

@app.cli.command("delete-alembic-db")
def delete_alembic_version():
    try:
        with app.app_context():
            db.session.execute(db.text("DELETE FROM alembic_version"))
            db.session.commit()
        print("Alembic version information deleted successfully.")
    except Exception as e:
        print(f"An error occurred: {e}")