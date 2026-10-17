"""
src/check_setup.py
------------------
Quick health check for the environment: Python and package versions, and a
test connection to PostgreSQL using the shared get_engine() from src/db.py.

Run from the project folder:
    python src/check_setup.py
"""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version

from sqlalchemy import text

from db import get_engine

PACKAGES = ("pandas", "sqlalchemy", "psycopg2-binary", "yfinance", "python-dotenv")


def main() -> int:
    print(f"Python: {sys.version.split()[0]}")
    for package in PACKAGES:
        try:
            print(f"  {package}: {version(package)}")
        except PackageNotFoundError:
            print(f"  {package}: NOT INSTALLED")
            return 1

    engine = get_engine()
    with engine.connect() as conn:
        pg_version = conn.execute(text("SELECT version()")).scalar_one()
        db_name, db_user = conn.execute(text("SELECT current_database(), current_user")).one()

    print(f"PostgreSQL: {pg_version.split(',')[0]}")
    print(f"Connected to database '{db_name}' as user '{db_user}'")
    print("Setup check: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
