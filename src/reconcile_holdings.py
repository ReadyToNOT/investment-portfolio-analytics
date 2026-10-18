"""
src/reconcile_holdings.py
-------------------------
Stage 4: an independent second calculation of shares held and market value.

vw_daily_holdings computes positions in SQL. This script recomputes the same
numbers in pandas straight from the CSV files (data/raw/prices_daily.csv and
data/processed/transactions.csv), without using any database table, and
compares the two row by row. If two different methods on the same inputs agree
on all ~8,900 rows, a logic error in either is very unlikely.

It also prints the AAPL rows used for the hand check in docs/reconciliation.md.

Run from the project folder (after build_model.py passes):
    python src/reconcile_holdings.py
"""

from __future__ import annotations

import sys

import pandas as pd

from config import TRANSACTIONS_CSV
from db import get_engine
from raw_io import PRICES_CSV

VALUE_TOLERANCE = 0.000001     # dollars; differences below this are rounding noise
HAND_CHECK_TICKER = "AAPL"
HAND_CHECK_DATES = ["2023-11-01", "2025-07-31", "2025-08-01"]   # plus the last date, added below


def positions_from_csv() -> pd.DataFrame:
    """Shares held and market value per holding per trading day, from the CSVs only."""
    prices = pd.read_csv(PRICES_CSV, parse_dates=["date"])
    trades = pd.read_csv(TRANSACTIONS_CSV, parse_dates=["trade_date"])
    trades["ticker"] = trades["ticker"].str.strip().str.upper()

    # + shares for a BUY, - shares for a SELL.
    sign = trades["transaction_type"].str.strip().str.upper().map({"BUY": 1, "SELL": -1})
    trades["signed_shares"] = trades["shares"] * sign

    # One number per ticker per trade date (combines same-day trades).
    daily = (
        trades.groupby(["ticker", "trade_date"], as_index=False)["signed_shares"].sum()
        .rename(columns={"trade_date": "date"})
    )

    # Only tickers that were traded (this drops SPY), on every trading day.
    held = prices[prices["ticker"].isin(daily["ticker"].unique())][["date", "ticker", "close"]]
    held = held.merge(daily, on=["ticker", "date"], how="left")   # left = keep every price row
    held["signed_shares"] = held["signed_shares"].fillna(0)
    held = held.sort_values(["ticker", "date"])

    # cumsum() = running total, done separately within each ticker by groupby.
    held["shares_held"] = held.groupby("ticker")["signed_shares"].cumsum()

    # Keep days from each ticker's first trade onward (same rule as the view).
    first_trade = daily.groupby("ticker")["date"].min()
    held = held[held["date"] >= held["ticker"].map(first_trade)]

    held["market_value"] = held["shares_held"] * held["close"]
    return held[["date", "ticker", "shares_held", "close", "market_value"]].reset_index(drop=True)


def positions_from_view() -> pd.DataFrame:
    engine = get_engine()
    query = """
        SELECT price_date AS date, ticker, shares_held, close_price, market_value
        FROM vw_daily_holdings
    """
    view = pd.read_sql(query, engine, parse_dates=["date"])
    # shares_held is NUMERIC in PostgreSQL and arrives as Python Decimal; make it a float.
    view["shares_held"] = view["shares_held"].astype(float)
    return view


def main() -> int:
    csv_side = positions_from_csv()
    db_side = positions_from_view()

    # An outer merge keeps rows that exist on only one side; indicator=True adds a
    # "_merge" column saying where each row came from (both / left_only / right_only).
    both = csv_side.merge(db_side, on=["date", "ticker"], how="outer",
                          suffixes=("_csv", "_db"), indicator=True)

    only_one_side = both[both["_merge"] != "both"]
    matched = both[both["_merge"] == "both"]
    share_diff = matched[matched["shares_held_csv"] != matched["shares_held_db"]]
    value_gap = (matched["market_value_csv"] - matched["market_value_db"]).abs()
    value_diff = matched[value_gap > VALUE_TOLERANCE]

    results = [
        ("Same row count", len(csv_side) == len(db_side), f"CSV {len(csv_side):,} / view {len(db_side):,}"),
        ("Every row on both sides", only_one_side.empty, f"{len(only_one_side)} rows on one side only"),
        ("Shares held identical on every row", share_diff.empty, f"{len(share_diff)} rows differ"),
        (f"Market value within ${VALUE_TOLERANCE} on every row", value_diff.empty,
         f"{len(value_diff)} rows differ; largest gap ${value_gap.max():.10f}"),
    ]

    print("Independent recalculation (pandas from CSVs) vs vw_daily_holdings:")
    failures = 0
    for name, ok, detail in results:
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}  ({detail})")

    # Rows for the hand check.
    last_date = csv_side["date"].max()
    dates = pd.to_datetime(HAND_CHECK_DATES + [last_date.strftime("%Y-%m-%d")])
    sample = csv_side[(csv_side["ticker"] == HAND_CHECK_TICKER) & (csv_side["date"].isin(dates))]
    print(f"\nHand-check rows for {HAND_CHECK_TICKER} (compare with docs/reconciliation.md):")
    print(sample.assign(date=sample["date"].dt.date).to_string(index=False, float_format=lambda x: f"{x:,.4f}"))

    print(f"\n{len(results) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
