"""
src/build_model.py
------------------
Stage 4: builds the reporting model from the stg_* staging tables, then
validates it.

Steps:
  1. Runs three SQL files inside ONE transaction (all-or-nothing):
       sql/03_create_model.sql   drop and re-create dim_*/fact_* tables
       sql/04_load_model.sql     fill them from the stg_* tables
       sql/05_create_views.sql   create vw_daily_holdings
     If any statement fails (for example a foreign-key violation), PostgreSQL
     rolls everything back and the previous model stays as it was.
  2. Prints the row count of every model table and the view.
  3. Runs sql/06_validate_model.sql and prints each PASS/FAIL line.

Exit code 0 = every check passed, 1 = at least one failed (same convention as
check_raw_data.py and load_staging.py).

Run from the project folder (after load_staging.py):
    python src/build_model.py
"""

from __future__ import annotations

import sys

from sqlalchemy import text

from db import get_engine
from raw_io import SQL_DIR

BUILD_FILES = ["03_create_model.sql", "04_load_model.sql", "05_create_views.sql"]
VALIDATION_FILE = "06_validate_model.sql"

MODEL_OBJECTS = [
    "dim_security",
    "dim_date",
    "fact_prices",
    "fact_transactions",
    "fact_rates",
    "vw_daily_holdings",
]


def read_sql(name: str) -> str:
    """
    Read one SQL file from sql/.
    The database driver (psycopg2) treats a percent sign as a placeholder
    marker, so a stray one in a SQL file (even in a comment) can break the run
    with a confusing error. We stop early with a clear message instead.
    """
    sql = (SQL_DIR / name).read_text(encoding="utf-8")
    if "%" in sql:
        raise ValueError(f"{name} contains a percent sign; write 'percent' instead.")
    return sql


def build(engine) -> None:
    """Run the three build files in one transaction."""
    # engine.begin(): commit at the end of the block, roll back on any error.
    with engine.begin() as conn:
        for name in BUILD_FILES:
            conn.exec_driver_sql(read_sql(name))
            print(f"Ran {name}")


def print_row_counts(engine) -> None:
    print("\nRow counts:")
    with engine.connect() as conn:
        for obj in MODEL_OBJECTS:
            n = conn.execute(text(f"SELECT COUNT(*) FROM {obj}")).scalar_one()
            print(f"  {obj:<20}{n:>8,}")


def validate(engine) -> int:
    """Run the validation query and print one line per check. Returns the number of failures."""
    with engine.connect() as conn:
        # .mappings() returns each row as a dictionary keyed by column name.
        rows = conn.exec_driver_sql(read_sql(VALIDATION_FILE)).mappings().all()

    print("\nValidation checks:")
    failures = 0
    for r in rows:
        ok = bool(r["passed"])
        failures += not ok
        line = f"{'PASS' if ok else 'FAIL'}  {r['check_id']}  {r['check_name']}"
        # Show the numbers on failures, and on passes that compare two totals
        # ("0 bad rows"-style checks are self-explanatory when they pass).
        if not ok or not r["expected"].startswith("0"):
            line += f"  (expected {r['expected']}, got {r['actual']})"
        print(line)

    print(f"\n{len(rows) - failures} passed, {failures} failed")
    return failures


def main() -> int:
    engine = get_engine()
    build(engine)
    print_row_counts(engine)
    failures = validate(engine)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
