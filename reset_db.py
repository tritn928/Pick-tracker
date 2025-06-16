# reset_db.py
import os
import subprocess
import getpass

# --- Configuration ---
# Replace with your PostgreSQL details
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "myapp_db"
DB_USER = "myapp_user"
# The superuser is needed to drop/create databases
DB_SUPERUSER = "postgres"
BACKUP_FILE = "backups/golden_backup.sql"


def run_command(command, password=None):
    """Runs a command-line command, optionally passing a password."""
    try:
        env = os.environ.copy()
        if password:
            env['PGPASSWORD'] = password

        # Using shell=True for simplicity, ensure command components are controlled
        process = subprocess.run(command, shell=True, check=True, capture_output=True, text=True, env=env)
        print("OK - Command successful.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR executing command: {e.cmd}")
        print(f"  Return Code: {e.returncode}")
        print(f"  Output: {e.stdout}")
        print(f"  Error Output: {e.stderr}")
        return False


def main():
    print("--- Starting Database Restore Process ---")

    # Securely prompt for the superuser password
    superuser_password = 'Jasonn928'
    if not superuser_password:
        print("No password entered. Aborting.")
        return

    # Step 1: Drop the existing database
    print(f"\n[1/3] Dropping database '{DB_NAME}'...")
    drop_command = f'dropdb -U {DB_SUPERUSER} -h {DB_HOST} -p {DB_PORT} --if-exists {DB_NAME}'
    if not run_command(drop_command, superuser_password):
        print("Failed to drop database. Aborting.")
        return

    # Step 2: Create a new, empty database
    print(f"\n[2/3] Creating database '{DB_NAME}'...")
    create_command = f'createdb -U {DB_SUPERUSER} -h {DB_HOST} -p {DB_PORT} -O {DB_USER} {DB_NAME}'
    if not run_command(create_command, superuser_password):
        print("Failed to create database. Aborting.")
        return

    # Step 3: Restore the database from the backup file
    print(f"\n[3/3] Restoring data from '{BACKUP_FILE}'...")
    restore_command = f'psql -U {DB_USER} -h {DB_HOST} -p {DB_PORT} -d {DB_NAME} -f {BACKUP_FILE}'
    # Prompt for the app user's password for the final step
    app_user_password = '123'
    if not run_command(restore_command, app_user_password):
        print("Failed to restore database.")
        return

    print("\n--- Database restore complete! ---")


if __name__ == "__main__":
    main()