"""
src/build_backtest.py
---------------------
Stage 6: the one command that rebuilds every backtest table.

Steps (same pattern as build_analysis.py):
  1. Reads the Stage 4/5 tables from PostgreSQL (backtest.load_inputs).
  2. Simulates S1 to S3 at 0, 10 and 25 bp (backtest.compute_all).
  3. Inside ONE transaction: runs sql/09_create_backtest_tables.sql (drop and
     re-create the 5 tables) and inserts every result. If anything fails,
     PostgreSQL rolls back and the previous results stay as they were.
  4. Reads the tables BACK from PostgreSQL and runs checks B01-B22
     (src/check_backtest.py).
  5. Prints the headline table and the cost sensitivity.

Exit code 0 = every check passed, 1 = at least one failed.

Run from the project folder, after build_analysis.py:
    python src/build_backtest.py
"""

from __future__ import annotations

import sys

import pandas as pd
from sqlalchemy import text

from backtest import COST_LEVELS_BPS, HEADLINE_BPS, STRATEGIES, compute_all, load_inputs
from build_model import read_sql
from check_backtest import run_checks
from db import get_engine

DDL_FILE = "09_create_backtest_tables.sql"

# dim_strategy first: the fact tables' foreign keys point at it.
TABLES = [
    "dim_strategy",
    "fact_backtest_daily",
    "fact_backtest_trades",
    "fact_backtest_summary",
    "fact_backtest_worst_drawdown",
]

DATE_COLUMNS = {
    "fact_backtest_daily": ["price_date"],
    "fact_backtest_trades": ["price_date"],
    "fact_backtest_worst_drawdown": ["peak_date", "trough_date", "recovery_date"],
}


def to_db_frame(name: str, df: pd.DataFrame) -> pd.DataFrame:
    """Copy of df with date columns as Python dates (NaT -> None = NULL)."""
    out = df.copy()
    for col in DATE_COLUMNS.get(name, []):
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
            df.to_sql(name, con=conn, if_exists="append", index=False,
                      method="multi", chunksize=1000)
            print(f"Loaded {len(df):>6,} rows into {name}")


def read_back(engine) -> dict[str, pd.DataFrame]:
    """Read every backtest table from PostgreSQL, so checks test what is stored."""
    out = {}
    with engine.connect() as conn:
        for name in TABLES:
            df = pd.read_sql(text(f"SELECT * FROM {name}"), conn)
            for col in DATE_COLUMNS.get(name, []):
                df[col] = pd.to_datetime(df[col])
            out[name] = df
    return out


def print_results(stored: dict[str, pd.DataFrame]) -> None:
    """Headline table (10 bp, plus references) and the cost sensitivity."""
    summ = stored["fact_backtest_summary"]
    names = stored["dim_strategy"].sort_values("sort_order")
    head = summ[summ["is_headline"]].pivot(index="strategy_code", columns="metric_key", values="value")

    print(f"\nHeadline results ({HEADLINE_BPS} bp trading cost; ACTUAL and SPY have no costs):")
    print(f"  {'Line':<30}{'Total':>9}{'Annual':>9}{'Vol':>8}{'Sharpe':>8}{'MaxDD':>9}"
          f"{'Beta':>7}{'Trades':>8}{'Costs $':>10}{'Cash':>7}")
    for code, name in zip(names["strategy_code"], names["strategy_name"]):
        m = head.loc[code]
        line = (f"  {name:<30}{m['total_return']:>9.2%}{m['annualized_return']:>9.2%}"
                f"{m['annualized_volatility']:>8.2%}{m['sharpe_ratio']:>8.2f}"
                f"{m['max_drawdown']:>9.2%}{m['beta']:>7.2f}")
        if code in STRATEGIES:
            line += (f"{m['trades_after_start']:>8.0f}{m['total_costs']:>10,.2f}"
                     f"{m['avg_cash_weight']:>7.1%}")
        print(line)

    print("\nCost sensitivity, total return:")
    print(f"  {'Strategy':<30}" + "".join(f"{str(b) + ' bp':>10}" for b in COST_LEVELS_BPS))
    tot = summ[summ["metric_key"] == "total_return"].pivot(index="strategy_code",
                                                           columns="cost_bps", values="value")
    for code, name in zip(names["strategy_code"], names["strategy_name"]):
        if code in STRATEGIES:
            print(f"  {name:<30}" + "".join(f"{tot.loc[code, b]:>10.2%}" for b in COST_LEVELS_BPS))


def main() -> int:
    engine = get_engine()

    inputs = load_inputs(engine)
    print(f"Read inputs: {len(inputs['portfolio'])} portfolio days, "
          f"{len(inputs['calendar'])} trading days incl. warm-up")

    result = compute_all(inputs)
    print(f"Trade dates: {len(result['trade_dates'])} month-ends "
          f"({result['trade_dates'][0].date()} to {result['trade_dates'][-1].date()}); "
          f"S3 decisions: {len(result['exec_dates'])}")
    load(engine, result["tables"])

    stored = read_back(engine)
    results = run_checks(inputs, result, stored)

    print("\nValidation checks:")
    failures = 0
    for cid, name, expected, actual, passed in results:
        failures += not passed
        print(f"{'PASS' if passed else 'FAIL'}  {cid}  {name}  (expected {expected}, got {actual})")
    print(f"\n{len(results) - failures} passed, {failures} failed")

    print_results(stored)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
