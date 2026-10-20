"""
src/build_analysis.py
---------------------
Stage 5: the one command that rebuilds every analysis table.

Steps:
  1. Reads the Stage 4 model from PostgreSQL (analysis.load_inputs).
  2. Computes all metrics in pandas (analysis.compute_all).
  3. Inside ONE transaction: runs sql/08_create_analysis_tables.sql (drop and
     re-create the 7 tables) and inserts every result. If anything fails,
     PostgreSQL rolls back and the previous results stay as they were.
  4. Reads the tables BACK from PostgreSQL and runs the PASS/FAIL checks in
     src/check_analysis.py on what was actually stored.

Exit code 0 = every check passed, 1 = at least one failed.

Run from the project folder, after build_model.py:
    python src/build_analysis.py
"""

from __future__ import annotations

import sys

import pandas as pd
from sqlalchemy import text

from analysis import compute_all, load_inputs
from build_model import read_sql
from check_analysis import run_checks
from db import get_engine

DDL_FILE = "08_create_analysis_tables.sql"

# Insert order follows the foreign keys only loosely (all point at dim_*),
# so any order works; this is just the order they are printed in.
TABLES = [
    "fact_daily_portfolio",
    "fact_daily_holding_returns",
    "fact_correlation",
    "fact_drawdown_episodes",
    "fact_risk_contribution",
    "fact_holding_beta",
    "analysis_summary",
]

# Columns that hold dates, per table. They are converted to plain Python
# dates before inserting (PostgreSQL DATE) and back to Timestamps after reading.
DATE_COLUMNS = {
    "fact_daily_portfolio": ["price_date", "rf_rate_date"],
    "fact_daily_holding_returns": ["price_date"],
    "fact_drawdown_episodes": ["peak_date", "trough_date", "recovery_date"],
    "fact_risk_contribution": ["window_start", "window_end"],
    "analysis_summary": ["period_start", "period_end"],
}


def to_db_frame(name: str, df: pd.DataFrame) -> pd.DataFrame:
    """Copy of df with date columns as Python dates (NaT -> None = NULL)."""
    out = df.copy()
    for col in DATE_COLUMNS.get(name, []):
        # .astype(object) lets the column hold None for missing dates.
        out[col] = pd.to_datetime(out[col]).dt.date.astype(object)
        out.loc[out[col].isna(), col] = None
    return out


def load(engine, tables: dict[str, pd.DataFrame]) -> None:
    """Drop/create the tables and insert all rows in one transaction."""
    with engine.begin() as conn:
        conn.exec_driver_sql(read_sql(DDL_FILE))
        print(f"Ran {DDL_FILE}")
        for name in TABLES:
            df = to_db_frame(name, tables[name])
            # if_exists="append": insert into the table sql/08 just created,
            # keeping its types, keys and foreign keys.
            df.to_sql(name, con=conn, if_exists="append", index=False,
                      method="multi", chunksize=1000)
            print(f"Loaded {len(df):>6,} rows into {name}")


def read_back(engine) -> dict[str, pd.DataFrame]:
    """Read every analysis table from PostgreSQL, so checks test what is stored."""
    out = {}
    with engine.connect() as conn:
        for name in TABLES:
            df = pd.read_sql(text(f"SELECT * FROM {name}"), conn)
            for col in DATE_COLUMNS.get(name, []):
                df[col] = pd.to_datetime(df[col])
            out[name] = df
    return out


def main() -> int:
    engine = get_engine()

    inputs = load_inputs(engine)
    print(f"Read inputs: {len(inputs['dates'])} portfolio trading days, "
          f"{len(inputs['holdings']):,} holding-day rows")

    tables = compute_all(inputs)
    load(engine, tables)

    stored = read_back(engine)
    results = run_checks(inputs, stored)

    print("\nValidation checks:")
    failures = 0
    for cid, name, expected, actual, passed in results:
        failures += not passed
        print(f"{'PASS' if passed else 'FAIL'}  {cid}  {name}  (expected {expected}, got {actual})")
    print(f"\n{len(results) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
