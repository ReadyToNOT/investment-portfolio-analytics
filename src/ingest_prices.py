"""
src/ingest_prices.py
--------------------
Downloads daily prices, dividends and splits from Yahoo Finance (via yfinance)
for every ticker in data/processed/security_lookup.csv (12 holdings + SPY),
from DOWNLOAD_START to the latest completed trading day.

Outputs (all overwritten on every run, never appended):
    data/raw/prices_daily.csv   date, ticker, open, high, low, close, adj_close, volume
    data/raw/dividends.csv      date, ticker, dividend_per_share
    data/raw/splits.csv         date, ticker, split_ratio
    data/raw/download_log.csv   rows for source = "yfinance" are refreshed

Close vs Adj Close (yfinance with auto_adjust=False):
    close      = the price the stock actually closed at that day (yfinance
                 does adjust it for splits, which is why we avoid split tickers).
                 Use it for "what was my position worth": shares x close.
    adj_close  = close, with every earlier day scaled DOWN for later dividends
                 (and splits). Day-to-day changes in adj_close equal the
                 return you'd get if you reinvested dividends. Use it for returns.

All-or-nothing: if any ticker fails, nothing is written, so old files stay valid.

Run from the project folder:
    python src/ingest_prices.py
"""

from __future__ import annotations

import sys
import time
from datetime import date, datetime, timedelta, timezone
from importlib.metadata import version
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from config import DOWNLOAD_START, SECURITY_LOOKUP_CSV
from raw_io import (
    DIVIDENDS_CSV,
    PRICES_CSV,
    SPLITS_CSV,
    as_timestamp,
    update_download_log,
    write_csv_atomic,
)

MAX_ATTEMPTS = 4                 # tries per ticker before giving up
BACKOFF_SECONDS = 15             # wait 15s, 30s, 45s between retries (longer each time)
PAUSE_BETWEEN_TICKERS = 2.0      # be polite to Yahoo; reduces rate-limit errors
NEW_YORK = ZoneInfo("America/New_York")
DATA_READY_HOUR_ET = 18          # after 6 pm ET we treat today's close as final

# Columns we need from Ticker.history(auto_adjust=False, actions=True)
REQUIRED_COLUMNS = {"Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"}


class LayoutChanged(RuntimeError):
    """yfinance returned data in a shape we don't expect. Retrying won't help."""


def load_tickers() -> list[str]:
    lookup = pd.read_csv(SECURITY_LOOKUP_CSV)
    tickers = lookup["ticker"].astype(str).str.strip().str.upper()
    if tickers.duplicated().any():
        raise ValueError(f"Duplicate tickers in {SECURITY_LOOKUP_CSV.name}")
    return sorted(tickers.tolist())


def end_date_exclusive() -> date:
    """
    yfinance's `end` is EXCLUSIVE (data up to the day before).
    Before 6 pm New York time, today's bar may still be moving, so we stop at
    yesterday. After 6 pm we include today.
    """
    now_et = datetime.now(NEW_YORK)
    if now_et.hour >= DATA_READY_HOUR_ET:
        return now_et.date() + timedelta(days=1)
    return now_et.date()


def fetch_history(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Download one ticker with retries. Raises RuntimeError with a clear message on failure."""
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            hist = yf.Ticker(ticker).history(
                start=start.isoformat(),
                end=end.isoformat(),
                interval="1d",
                auto_adjust=False,   # keep BOTH Close and Adj Close (default is True)
                actions=True,        # include Dividends and Stock Splits columns
                repair=False,        # we want Yahoo's data as-is; our checks catch problems
            )
            if hist is None or hist.empty:
                raise ValueError("yfinance returned no rows")
            missing = REQUIRED_COLUMNS - set(hist.columns)
            if missing:
                raise LayoutChanged(
                    f"{ticker}: columns {sorted(missing)} missing. Got {list(hist.columns)}. "
                    "yfinance may have changed; paste this error into the chat."
                )
            return hist
        except LayoutChanged:
            raise
        except Exception as exc:  # network errors, rate limits (YFRateLimitError), empty data
            last_error = exc
            if attempt < MAX_ATTEMPTS:
                wait = BACKOFF_SECONDS * attempt
                print(f"    attempt {attempt} failed ({type(exc).__name__}: {exc}); retrying in {wait}s")
                time.sleep(wait)
    raise RuntimeError(
        f"{ticker}: download failed after {MAX_ATTEMPTS} attempts. Last error: "
        f"{type(last_error).__name__}: {last_error}. If every ticker fails this way, "
        "Yahoo may be blocking or rate-limiting; wait an hour and retry, or see the "
        "Stooq fallback notes."
    )


def tidy(ticker: str, hist: pd.DataFrame, start: date) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Turn yfinance's wide table into our three long tables (prices, dividends, splits)."""
    index = hist.index
    # yfinance dates carry a time zone (New York). We only want the calendar date.
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    dates = pd.DatetimeIndex(index).normalize()

    # .to_numpy() copies plain values so nothing depends on index alignment.
    frame = pd.DataFrame(
        {
            "date": dates,
            "ticker": ticker,
            "open": hist["Open"].to_numpy(),
            "high": hist["High"].to_numpy(),
            "low": hist["Low"].to_numpy(),
            "close": hist["Close"].to_numpy(),
            "adj_close": hist["Adj Close"].to_numpy(),
            "volume": hist["Volume"].to_numpy(),
            "dividend": hist["Dividends"].to_numpy(),
            "split": hist["Stock Splits"].to_numpy(),
        }
    )
    frame = frame[frame["date"] >= as_timestamp(start)]

    prices = frame[["date", "ticker", "open", "high", "low", "close", "adj_close", "volume"]]
    dividends = frame.loc[frame["dividend"].fillna(0) != 0, ["date", "ticker", "dividend"]].rename(
        columns={"dividend": "dividend_per_share"}
    )
    splits = frame.loc[frame["split"].fillna(0) != 0, ["date", "ticker", "split"]].rename(
        columns={"split": "split_ratio"}
    )
    return prices, dividends, splits


def main() -> int:
    start = as_timestamp(DOWNLOAD_START).date()
    end = end_date_exclusive()
    tickers = load_tickers()
    yf_version = version("yfinance")

    print(f"yfinance {yf_version}: {len(tickers)} tickers, {start} to {end} (end exclusive)")

    all_prices, all_dividends, all_splits, log_rows = [], [], [], []
    for i, ticker in enumerate(tickers, start=1):
        print(f"[{i:>2}/{len(tickers)}] {ticker}")
        try:
            hist = fetch_history(ticker, start, end)
        except (RuntimeError, LayoutChanged) as exc:
            print(f"\nFAILED: {exc}")
            print("Nothing was written; your existing raw files are unchanged.")
            return 1

        prices, dividends, splits = tidy(ticker, hist, start)
        all_prices.append(prices)
        all_dividends.append(dividends)
        all_splits.append(splits)
        log_rows.append(
            {
                "source": "yfinance",
                "series": ticker,
                "rows": len(prices),
                "first_date": prices["date"].min().date(),
                "last_date": prices["date"].max().date(),
                "requested_start": start,
                "requested_end": end - timedelta(days=1),
                "downloaded_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "library": "yfinance",
                "library_version": yf_version,
            }
        )
        if i < len(tickers):
            time.sleep(PAUSE_BETWEEN_TICKERS)

    # One combined file per table, sorted so re-runs produce stable, diff-able files.
    def finish(parts: list[pd.DataFrame]) -> pd.DataFrame:
        df = pd.concat(parts, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")
        return df

    prices_df = finish(all_prices)
    dividends_df = finish(all_dividends)
    splits_df = finish(all_splits)

    write_csv_atomic(prices_df, PRICES_CSV)
    write_csv_atomic(dividends_df, DIVIDENDS_CSV)
    write_csv_atomic(splits_df, SPLITS_CSV)
    update_download_log("yfinance", log_rows)

    summary = pd.DataFrame(log_rows)[["series", "rows", "first_date", "last_date"]]
    print("\n" + summary.to_string(index=False))
    print(f"\nWrote {len(prices_df):,} price rows      -> {PRICES_CSV.name}")
    print(f"Wrote {len(dividends_df):,} dividend rows    -> {DIVIDENDS_CSV.name}")
    print(f"Wrote {len(splits_df):,} split rows        -> {SPLITS_CSV.name}")
    if len(splits_df):
        print("WARNING: splits found inside the window. Run check_raw_data.py and report back.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
