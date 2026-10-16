"""
check_setup.py
Confirms that (1) the key packages import correctly and
(2) Python can log in to the PostgreSQL database using the .env settings.
Run it from the project root:  python src/check_setup.py
"""

import os
import sys
from pathlib import Path

import pandas as pd
import sqlalchemy
import yfinance
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# The project root is one folder above src/. Building the path this way means
# the script works no matter which folder you run it from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Read the key=value lines from .env into environment variables.
load_dotenv(PROJECT_ROOT / ".env")


def get_engine():
    """Build a SQLAlchemy 'engine' (a reusable database connection factory)."""
    required = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        sys.exit(f"Missing values in .env: {', '.join(missing)}")

    # URL.create safely handles special characters (like @ or #) in passwords.
    url = URL.create(
        drivername="postgresql+psycopg2",
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        database=os.getenv("DB_NAME"),
    )
    return create_engine(url)


def main():
    print("Python        :", sys.version.split()[0])
    print("pandas        :", pd.__version__)
    print("SQLAlchemy    :", sqlalchemy.__version__)
    print("yfinance      :", yfinance.__version__)

    engine = get_engine()
    with engine.connect() as conn:
        db_name = conn.execute(text("SELECT current_database()")).scalar()
        pg_version = conn.execute(text("SHOW server_version")).scalar()
        # Prove we are allowed to create tables, then clean up after ourselves.
        conn.execute(text("CREATE TABLE IF NOT EXISTS _setup_test (id INT)"))
        conn.execute(text("DROP TABLE _setup_test"))
        conn.commit()

    print("Connected to  :", db_name)
    print("PostgreSQL    :", pg_version)
    print("Create/drop table permission: OK")
    print("\nSetup check passed.")


if __name__ == "__main__":
    main()