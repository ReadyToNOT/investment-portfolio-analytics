"""
src/raw_io.py
-------------
Shared file locations and small helpers for the raw data files (Stage 3).

Why a separate module instead of editing config.py: these paths are used by
four scripts, so they live in one place. If you'd rather keep everything in
config.py, we can fold them in at Stage 4 (paste config.py and I'll merge it).
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from config import DOWNLOAD_START, PROJECT_ROOT

RAW_DIR = Path(PROJECT_ROOT) / "data" / "raw"
SQL_DIR = Path(PROJECT_ROOT) / "sql"

PRICES_CSV = RAW_DIR / "prices_daily.csv"      # all tickers, one row per ticker per day
DIVIDENDS_CSV = RAW_DIR / "dividends.csv"      # one row per ex-dividend date per ticker
SPLITS_CSV = RAW_DIR / "splits.csv"            # one row per split per ticker (expected empty)
RATES_CSV = RAW_DIR / "fred_dtb3.csv"          # FRED file saved byte-for-byte as downloaded
DOWNLOAD_LOG_CSV = RAW_DIR / "download_log.csv"

LOG_COLUMNS = [
    "source",               # "yfinance" or "FRED"
    "series",               # ticker symbol or FRED series ID
    "rows",                 # rows saved for that series inside the window
    "first_date",
    "last_date",
    "requested_start",
    "requested_end",
    "downloaded_at_utc",
    "library",
    "library_version",
]


def as_timestamp(value) -> pd.Timestamp:
    """Turn a date, string or Timestamp into a midnight pandas Timestamp."""
    return pd.Timestamp(value).normalize()


def write_csv_atomic(df: pd.DataFrame, path: Path) -> None:
    """
    Write a CSV to a temporary file, then swap it into place.
    If anything fails mid-write, the previous good file is untouched.
    Writing the whole file each run (never appending) means re-runs can't
    create duplicate rows.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.to_csv(tmp, index=False, lineterminator="\n")
    os.replace(tmp, path)


def write_bytes_atomic(data: bytes, path: Path) -> None:
    """Same idea as write_csv_atomic, for a file we save exactly as downloaded."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def update_download_log(source: str, rows: list[dict]) -> None:
    """
    Replace this source's rows in download_log.csv and keep the other source's rows.
    So ingest_prices.py and ingest_rates.py can each refresh their own part.
    """
    new = pd.DataFrame(rows, columns=LOG_COLUMNS).astype(str)
    if DOWNLOAD_LOG_CSV.exists():
        old = pd.read_csv(DOWNLOAD_LOG_CSV, dtype=str)
        old = old[old["source"] != source]
        combined = pd.concat([old, new], ignore_index=True) if not old.empty else new
    else:
        combined = new
    combined = combined.sort_values(["source", "series"]).reset_index(drop=True)
    write_csv_atomic(combined, DOWNLOAD_LOG_CSV)


def read_dtb3(path: Path = RATES_CSV) -> pd.DataFrame:
    """
    Parse the raw FRED file into two columns: rate_date and dtb3_pct.

    FRED marks days with no value (e.g. bond-market holidays). Older downloads
    used "." for these; newer ones may leave the cell blank (unverified which
    one you'll get). We treat both as missing (NaN), never as zero.
    Only rows on or after DOWNLOAD_START are kept.
    """
    raw = pd.read_csv(path, na_values=["."])
    if raw.shape[1] < 2 or "DTB3" not in raw.columns:
        raise ValueError(
            f"{path.name} doesn't look like a FRED DTB3 file. Columns found: {list(raw.columns)}"
        )
    date_col = raw.columns[0]  # "observation_date" in current files, "DATE" in older ones
    out = pd.DataFrame(
        {
            "rate_date": pd.to_datetime(raw[date_col], format="%Y-%m-%d"),
            # errors="coerce": anything that isn't a number becomes NaN (missing)
            "dtb3_pct": pd.to_numeric(raw["DTB3"], errors="coerce"),
        }
    )
    out = out[out["rate_date"] >= as_timestamp(DOWNLOAD_START)]
    return out.sort_values("rate_date").reset_index(drop=True)
