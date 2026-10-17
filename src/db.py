"""
src/db.py
---------
One shared place that knows how to connect to PostgreSQL.

Every script that needs the database does:
    from db import get_engine
    engine = get_engine()

An "engine" (SQLAlchemy term) is a reusable connection factory: it holds the
connection details and hands out connections when a script asks for one.

Credentials come ONLY from the .env file in the project root (git-ignored).
Nothing secret is written in this file.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine

# Project root = the folder above src/. Works no matter where you run from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

# Every one of these must be set in .env.
REQUIRED_VARS = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")


def get_engine() -> Engine:
    """Build a SQLAlchemy engine for the portfolio_analytics database from .env."""
    if not ENV_FILE.exists():
        raise FileNotFoundError(
            f".env not found at {ENV_FILE}. Copy .env.example to .env and fill it in."
        )

    # Reads KEY=VALUE lines from .env into environment variables.
    load_dotenv(ENV_FILE)

    missing = [name for name in REQUIRED_VARS if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"These variables are missing or empty in .env: {', '.join(missing)}")

    # URL.create builds the connection address safely: special characters in the
    # password (like @ or :) are escaped for us, so we never hand-build the string.
    url = URL.create(
        drivername="postgresql+psycopg2",
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        database=os.getenv("DB_NAME"),
    )

    # pool_pre_ping=True quietly tests a connection before using it, so a
    # connection that went stale (e.g. PostgreSQL restarted) is replaced.
    return create_engine(url, pool_pre_ping=True)
