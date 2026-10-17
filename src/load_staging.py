"""
src/load_staging.py
-------------------
Loads the raw CSVs (prices, dividends, splits, DTB3, download log) and the two
Stage 2 input CSVs (security lookup, transactions) into PostgreSQL staging
tables named stg_*.

Re-running replaces the data instead of duplicating it:
  1. sql/01_create_staging.sql creates the tables if they don't exist yet.
  2. Inside ONE transaction, every stg_* table is emptied (TRUNCATE) and
     refilled. A transaction is all-or-nothing: if any insert fails, PostgreSQL
     rolls everything back and the old data stays as it was.
  3. Row counts in the database are compared with the CSVs.

Run from the project folder (after check_raw_data.py passes):
    python src/load_staging.py
"""

from __future__ import annotations

import sys

import pandas as pd
from sqlalchemy import text

from config import SECURITY_LOOKUP_CSV, TRANSACTIONS_CSV
from db import get_engine
from raw_io import (
    DIVIDENDS_CSV,
    DOWNLOAD_LOG_CSV,
    PRICES_CSV,
    RATES_CSV,
    SPLITS_CSV,
    SQL_DIR,
    read_dtb3,
)

DDL_FILE = SQL_DIR / "01_create_staging.sql"


def to_date(series: pd.Series) -> pd.Series:
    """Text like '2023-11-01' -> Python date objects, which map to PostgreSQL DATE."""
    return pd.to_datetime(series, format="%Y-%m-%d").dt.date


def build_frames() -> dict[str, pd.DataFrame]:
    """Read each CSV and shape it to match its staging table's columns."""
    prices = pd.read_csv(PRICES_CSV)
    prices = pd.DataFrame(
        {
            "price_date": to_date(prices["date"]),
            "ticker": prices["ticker"],
            "open_price": prices["open"],
            "high_price": prices["high"],
            "low_price": prices["low"],
            "close_price": prices["close"],
            "adj_close_price": prices["adj_close"],
            "volume": prices["volume"].round().astype("Int64"),  # Int64 = whole numbers that allow blanks
        }
    )

    dividends = pd.read_csv(DIVIDENDS_CSV)
    dividends = pd.DataFrame(
        {
            "ex_date": to_date(dividends["date"]),
            "ticker": dividends["ticker"],
            "dividend_per_share": dividends["dividend_per_share"],
        }
    )

    splits = pd.read_csv(SPLITS_CSV)
    splits = pd.DataFrame(
        {
            "split_date": to_date(splits["date"]) if len(splits) else pd.Series(dtype="object"),
            "ticker": splits["ticker"],
            "split_ratio": splits["split_ratio"],
        }
    )

    rates = read_dtb3(RATES_CSV)
    rates["rate_date"] = rates["rate_date"].dt.date

    lookup = pd.read_csv(SECURITY_LOOKUP_CSV)
    lookup["ticker"] = lookup["ticker"].astype(str).str.strip().str.upper()
    lookup = lookup[["ticker", "security_name", "asset_class", "sector", "role", "target_weight_pct", "currency"]]

    trades = pd.read_csv(TRANSACTIONS_CSV)
    trades = pd.DataFrame(
        {
            "transaction_id": trades["transaction_id"].astype(str),
            "trade_date": to_date(trades["trade_date"]),
            "ticker": trades["ticker"].astype(str).str.strip().str.upper(),
            "transaction_type": trades["transaction_type"].astype(str).str.strip().str.upper(),
            "shares": trades["shares"],
        }
    )

    log = pd.read_csv(DOWNLOAD_LOG_CSV, dtype=str)
    log = log.rename(columns={"rows": "row_count"})  # ROWS is an SQL keyword, so the column is row_count
    log["row_count"] = pd.to_numeric(log["row_count"]).astype("Int64")
    log["first_date"] = to_date(log["first_date"])
    log["last_date"] = to_date(log["last_date"])
    log["downloaded_at_utc"] = pd.to_datetime(log["downloaded_at_utc"])

    return {
        "stg_prices": prices,
        "stg_dividends": dividends,
        "stg_splits": splits,
        "stg_rates": rates,
        "stg_security_lookup": lookup,
        "stg_transactions": trades,
        "stg_download_log": log,
    }


def main() -> int:
    frames = build_frames()
    engine = get_engine()

    # engine.begin() opens a transaction: commit at the end of the block,
    # automatic rollback if any line inside raises an error.
    with engine.begin() as conn:
        conn.exec_driver_sql(DDL_FILE.read_text(encoding="utf-8"))
        conn.exec_driver_sql("TRUNCATE TABLE " + ", ".join(frames) + ";")
        for table, df in frames.items():
            # if_exists="append" inserts into the table we created (keeping its
            # types and primary key) rather than letting pandas invent a new one.
            df.to_sql(table, con=conn, if_exists="append", index=False, method="multi", chunksize=1000)
            print(f"Loaded {len(df):>6,} rows into {table}")

    # Confirm the database holds exactly what the CSVs hold.
    print("\nRow count check:")
    failures = 0
    with engine.connect() as conn:
        for table, df in frames.items():
            db_rows = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            ok = db_rows == len(df)
            failures += not ok
            print(f"{'PASS' if ok else 'FAIL'}  {table}: CSV {len(df):,} / database {db_rows:,}")

    print(f"\n{len(frames) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
