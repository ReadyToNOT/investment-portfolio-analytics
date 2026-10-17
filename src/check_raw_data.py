"""
src/check_raw_data.py
---------------------
Checks the raw files from ingest_prices.py and ingest_rates.py BEFORE anything
goes into PostgreSQL. Each check prints PASS or FAIL; INFO lines are facts to
read, not tests. Exits with code 1 if any check fails.

Run from the project folder:
    python src/check_raw_data.py
"""

from __future__ import annotations

import sys
from datetime import date

import pandas as pd

from config import (
    BENCHMARK_TICKER,
    DOWNLOAD_START,
    NYSE_HOLIDAYS,
    PORTFOLIO_START,
    SECURITY_LOOKUP_CSV,
    TRANSACTIONS_CSV,
    WARMUP_TRADING_DAYS_NEEDED,
)
from raw_io import (
    DIVIDENDS_CSV,
    DOWNLOAD_LOG_CSV,
    PRICES_CSV,
    RATES_CSV,
    SPLITS_CSV,
    as_timestamp,
    read_dtb3,
)

PRICE_COLUMNS = ["open", "high", "low", "close", "adj_close"]
WEIGHT_TOLERANCE_PP = 2.0          # percentage points
HOLIDAY_CHECK_YEARS = (2023, 2024, 2025)

results: list[tuple[str, bool]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    """Record and print one PASS/FAIL line."""
    results.append((name, passed))
    print(f"{'PASS' if passed else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def info(text: str) -> None:
    print(f"INFO  {text}")


def main() -> int:
    # ---------- 0. Files exist ----------------------------------------------
    files = [PRICES_CSV, DIVIDENDS_CSV, SPLITS_CSV, RATES_CSV, DOWNLOAD_LOG_CSV]
    missing_files = [f.name for f in files if not f.exists()]
    check("All raw files exist", not missing_files, ", ".join(missing_files))
    if missing_files:
        return 1

    prices = pd.read_csv(PRICES_CSV, parse_dates=["date"])
    dividends = pd.read_csv(DIVIDENDS_CSV, parse_dates=["date"])
    splits = pd.read_csv(SPLITS_CSV, parse_dates=["date"])
    lookup = pd.read_csv(SECURITY_LOOKUP_CSV)
    trades = pd.read_csv(TRANSACTIONS_CSV, parse_dates=["trade_date"])
    lookup["ticker"] = lookup["ticker"].astype(str).str.strip().str.upper()
    trades["ticker"] = trades["ticker"].astype(str).str.strip().str.upper()

    download_start = as_timestamp(DOWNLOAD_START)
    portfolio_start = as_timestamp(PORTFOLIO_START)
    today = pd.Timestamp(date.today())

    # ---------- 1. Tickers ---------------------------------------------------
    expected = set(lookup["ticker"])
    found = set(prices["ticker"])
    check("Every lookup ticker has prices", expected <= found, f"missing: {sorted(expected - found)}")
    check("No unexpected tickers in prices", found <= expected, f"extra: {sorted(found - expected)}")

    # ---------- 2. Duplicates and bad prices --------------------------------
    dupes = prices.duplicated(["ticker", "date"]).sum()
    check("No duplicate (ticker, date) rows", dupes == 0, f"{dupes} duplicates")

    blanks = prices[PRICE_COLUMNS].isna().sum().sum()
    check("No blank prices", blanks == 0, f"{blanks} blank cells")
    non_positive = (prices[PRICE_COLUMNS] <= 0).sum().sum()
    check("No zero or negative prices", non_positive == 0, f"{non_positive} cells <= 0")
    if blanks or non_positive:
        bad = prices[prices[PRICE_COLUMNS].isna().any(axis=1) | (prices[PRICE_COLUMNS] <= 0).any(axis=1)]
        print(bad.head(10).to_string(index=False))

    # Adjusted close should never be above close (dividends only push past prices down).
    # Tiny tolerance for rounding in Yahoo's data.
    above = (prices["adj_close"] > prices["close"] * 1.0005).sum()
    check("adj_close <= close on every row", above == 0, f"{above} rows above")

    # ---------- 3. Calendar coverage vs SPY ---------------------------------
    spy_dates = set(prices.loc[prices["ticker"] == BENCHMARK_TICKER, "date"])
    if not spy_dates:
        check(f"{BENCHMARK_TICKER} present", False)
        return 1
    spy_first, spy_last = min(spy_dates), max(spy_dates)
    info(f"{BENCHMARK_TICKER} covers {spy_first.date()} to {spy_last.date()}, {len(spy_dates)} trading days")
    check("SPY starts within 4 days of DOWNLOAD_START",
          0 <= (spy_first - download_start).days <= 4, f"first date {spy_first.date()}")
    check("SPY data is recent (last date within 5 days of today)",
          (today - spy_last).days <= 5, f"last date {spy_last.date()}")

    for ticker in sorted(expected - {BENCHMARK_TICKER}):
        t_dates = set(prices.loc[prices["ticker"] == ticker, "date"])
        missing = sorted(spy_dates - t_dates)
        extra = sorted(t_dates - spy_dates)
        detail = ""
        if missing:
            detail += f"missing {len(missing)} SPY days, e.g. {[d.date() for d in missing[:3]]} "
        if extra:
            detail += f"{len(extra)} days SPY doesn't have, e.g. {[d.date() for d in extra[:3]]}"
        check(f"{ticker} has exactly SPY's trading days", not missing and not extra, detail.strip())

    # ---------- 4. Splits ---------------------------------------------------
    window_splits = splits[splits["date"] >= download_start]
    check("No stock splits inside the data window", window_splits.empty,
          "STOP and report these rows" if not window_splits.empty else "")
    if not window_splits.empty:
        print(window_splits.to_string(index=False))

    # ---------- 5. Dividends (facts, plus one sanity check) ----------------
    div_counts = dividends.groupby("ticker").size().reindex(sorted(expected), fill_value=0)
    info("Dividend payments in window per ticker: "
         + ", ".join(f"{t} {n}" for t, n in div_counts.items()))
    off_calendar = dividends[~dividends["date"].isin(spy_dates)]
    check("Every dividend ex-date is a trading day", off_calendar.empty, f"{len(off_calendar)} rows")

    # ---------- 6. Trade dates ----------------------------------------------
    bad_days = sorted(set(trades.loc[~trades["trade_date"].isin(spy_dates), "trade_date"]))
    check("Every trade date is a trading day", not bad_days, f"{[d.date() for d in bad_days]}")
    priced = trades.merge(prices, left_on=["ticker", "trade_date"], right_on=["ticker", "date"], how="left")
    unpriced = priced[priced["close"].isna()]
    check("Every trade has a closing price", unpriced.empty,
          f"{unpriced[['transaction_id', 'ticker', 'trade_date']].to_dict('records')}")

    # ---------- 7. NYSE holidays vs SPY's actual calendar -------------------
    config_holidays = {as_timestamp(d) for d in NYSE_HOLIDAYS}
    all_ok = True
    corrected: list[pd.Timestamp] = []
    for year in HOLIDAY_CHECK_YEARS:
        weekdays = pd.bdate_range(f"{year}-01-01", f"{year}-12-31")   # Mon-Fri only
        closed = {d for d in weekdays if d not in spy_dates}
        configured = {d for d in config_holidays if d.year == year}
        ok = closed == configured
        all_ok &= ok
        corrected.extend(sorted(closed))
        detail = ""
        if not ok:
            detail = (f"in data but not config: {[d.date() for d in sorted(closed - configured)]}; "
                      f"in config but not data: {[d.date() for d in sorted(configured - closed)]}")
        check(f"config.NYSE_HOLIDAYS matches SPY closures for {year}", ok, detail)

    # 2026 so far (only up to SPY's last date)
    weekdays_2026 = pd.bdate_range("2026-01-01", spy_last)
    closed_2026 = {d for d in weekdays_2026 if d not in spy_dates}
    configured_2026 = {d for d in config_holidays if d.year == 2026 and d <= spy_last}
    check("config.NYSE_HOLIDAYS matches SPY closures for 2026 so far", closed_2026 == configured_2026,
          f"data: {[d.date() for d in sorted(closed_2026)]}, config: {[d.date() for d in sorted(configured_2026)]}")

    # December 2022 sits inside the warm-up window but outside HOLIDAY_YEARS_COVERED.
    closed_dec_2022 = [d.date() for d in pd.bdate_range(download_start, "2022-12-31") if d not in spy_dates]
    info(f"Weekday closures between DOWNLOAD_START and 2022-12-31: {closed_dec_2022}")

    if not all_ok:
        print("\nCorrected 2023-2025 holidays (from SPY's actual calendar). Paste config.py into the chat")
        print("and I'll give you the whole corrected file. Dates:")
        for d in corrected:
            print(f"    date({d.year}, {d.month}, {d.day}),")

    warmup_days = sum(1 for d in spy_dates if d < portfolio_start)
    check(f"Warm-up trading days before PORTFOLIO_START >= {WARMUP_TRADING_DAYS_NEEDED}",
          warmup_days >= WARMUP_TRADING_DAYS_NEEDED,
          f"{warmup_days} actual (validate_inputs.py estimated 230)")

    # ---------- 8. Risk-free rate -------------------------------------------
    rates = read_dtb3(RATES_CSV)
    n_missing = int(rates["dtb3_pct"].isna().sum())
    info(f"DTB3: {len(rates)} rows {rates['rate_date'].min().date()} to "
         f"{rates['rate_date'].max().date()}, {n_missing} missing values")
    valid = rates["dtb3_pct"].dropna()
    check("DTB3 values are between 0% and 10%", bool(((valid >= 0) & (valid <= 10)).all()))
    check("DTB3 starts by DOWNLOAD_START + 4 days",
          (rates["rate_date"].min() - download_start).days <= 4)
    check("DTB3 is recent (last date within 10 days of today)",
          (today - rates["rate_date"].max()).days <= 10, f"last {rates['rate_date'].max().date()}")
    no_rate_days = len(spy_dates - set(rates.dropna()["rate_date"]))
    info(f"Trading days with no DTB3 value (will be forward-filled in Stage 5): {no_rate_days}")

    # ---------- 9. Starting weights vs targets ------------------------------
    initial = trades[(trades["trade_date"] == portfolio_start) & (trades["transaction_type"] == "BUY")]
    start_close = prices[prices["date"] == portfolio_start][["ticker", "close"]]
    w = (initial[["ticker", "shares"]]
         .merge(start_close, on="ticker", how="left")
         .merge(lookup[["ticker", "target_weight_pct"]], on="ticker", how="left"))
    w["value"] = w["shares"] * w["close"]
    total = w["value"].sum()
    w["actual_pct"] = 100 * w["value"] / total
    w["diff_pp"] = w["actual_pct"] - w["target_weight_pct"]
    w = w.sort_values("ticker")

    print(f"\nStarting weights on {portfolio_start.date()} (shares x unadjusted close). "
          f"Total value: ${total:,.2f}")
    print(w[["ticker", "shares", "close", "value", "target_weight_pct", "actual_pct", "diff_pp"]]
          .to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

    worst = w["diff_pp"].abs().max()
    off = w[w["diff_pp"].abs() > WEIGHT_TOLERANCE_PP]
    check(f"Every starting weight within {WEIGHT_TOLERANCE_PP} pp of target", off.empty,
          f"largest gap {worst:.2f} pp")

    if not off.empty:
        # Same total value, shares re-sized to target using the real closing prices.
        w["proposed_shares"] = (w["target_weight_pct"] / 100 * total / w["close"]).round().clip(lower=1).astype(int)
        w["proposed_value"] = w["proposed_shares"] * w["close"]
        w["proposed_pct"] = 100 * w["proposed_value"] / w["proposed_value"].sum()
        w["proposed_diff_pp"] = w["proposed_pct"] - w["target_weight_pct"]
        print("\nPROPOSED initial-buy share counts (only the 2023-11-01 rows change):")
        print(w[["ticker", "shares", "proposed_shares", "target_weight_pct", "proposed_pct", "proposed_diff_pp"]]
              .to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
        print(f"Proposed total: ${w['proposed_value'].sum():,.2f}")

    # ---------- Summary -----------------------------------------------------
    n_fail = sum(1 for _, ok in results if not ok)
    print(f"\n{len(results) - n_fail} passed, {n_fail} failed")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
