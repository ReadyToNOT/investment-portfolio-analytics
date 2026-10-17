"""
src/ingest_rates.py
-------------------
Downloads the FRED series DTB3 (3-Month Treasury Bill Secondary Market Rate,
Discount Basis, daily, percent per year) through FRED's official API and saves
it to data/raw/fred_dtb3.csv.

Why the API and not the fredgraph.csv link: the keyless CSV link has been
timing out or refusing scripted requests since mid-2026. The API needs a free
key but is FRED's supported route.

One-time setup:
  1. Get a free key: https://fred.stlouisfed.org/docs/api/api_key.html
  2. Add this line to .env (never to code, never to git):
         FRED_API_KEY=your32characterkeyhere

Output layout (same as FRED's CSV download, so raw_io.read_dtb3() reads it as-is):
    observation_date,DTB3
    2022-12-01,4.21
    2022-12-26,.        <- "." = no value that day (FRED's missing marker)

Stage 5 plan: convert the discount-basis yearly rate to an annual yield, then
to a per-trading-day rate, and forward-fill missing days.

Run from the project folder:
    python src/ingest_rates.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import pandas as pd
from dotenv import load_dotenv

from config import DOWNLOAD_START, PROJECT_ROOT, RISK_FREE_SERIES_ID
from raw_io import RATES_CSV, as_timestamp, read_dtb3, update_download_log, write_csv_atomic

API_URL = "https://api.stlouisfed.org/fred/series/observations"
MAX_ATTEMPTS = 3
WAIT_SECONDS = 10
TIMEOUT_SECONDS = 30


def fetch_observations(api_key: str) -> list[dict]:
    """Call the FRED API (retrying a few times) and return its list of {date, value} rows."""
    params = {
        "series_id": RISK_FREE_SERIES_ID,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": as_timestamp(DOWNLOAD_START).date().isoformat(),
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read())["observations"]
        except urllib.error.HTTPError as exc:
            # 4xx = the request itself is wrong (almost always the key). Retrying won't help.
            if 400 <= exc.code < 500:
                raise RuntimeError(f"FRED refused the request (HTTP {exc.code}). Check FRED_API_KEY in .env.")
            error = exc
        except Exception as exc:  # timeouts, dropped connections, bad responses
            error = exc
        if attempt < MAX_ATTEMPTS:
            print(f"  attempt {attempt} failed ({error}); retrying in {WAIT_SECONDS}s")
            time.sleep(WAIT_SECONDS)
    raise RuntimeError(f"FRED download failed after {MAX_ATTEMPTS} attempts: {error}")


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("FRED_API_KEY", "").strip()
    if not api_key:
        print("FAILED: add FRED_API_KEY=... to .env (free key: https://fred.stlouisfed.org/docs/api/api_key.html)")
        return 1

    # The URL contains the key, so we print a description instead of the URL.
    print(f"Downloading FRED {RISK_FREE_SERIES_ID} from {as_timestamp(DOWNLOAD_START).date()} via the FRED API")
    try:
        observations = fetch_observations(api_key)
    except RuntimeError as exc:
        print(f"FAILED: {exc}\nNothing was written.")
        return 1

    # Save FRED's values exactly as sent (as text, "." included).
    raw = pd.DataFrame(
        {
            "observation_date": [obs["date"] for obs in observations],
            RISK_FREE_SERIES_ID: [obs["value"] for obs in observations],
        }
    )
    write_csv_atomic(raw, RATES_CSV)

    # Read it back with the shared parser so a bad file is caught now.
    rates = read_dtb3(RATES_CSV)
    if rates.empty:
        print("FAILED: no DTB3 rows on or after DOWNLOAD_START.")
        return 1

    update_download_log(
        "FRED",
        [
            {
                "source": "FRED",
                "series": RISK_FREE_SERIES_ID,
                "rows": len(rates),
                "first_date": rates["rate_date"].min().date(),
                "last_date": rates["rate_date"].max().date(),
                "requested_start": as_timestamp(DOWNLOAD_START).date(),
                "requested_end": "latest",
                "downloaded_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "library": "FRED API (urllib)",
                "library_version": sys.version.split()[0],
            }
        ],
    )

    valid = rates.dropna()
    print(f"Saved {RATES_CSV.name}: {len(rates):,} rows, "
          f"{rates['rate_date'].min().date()} to {rates['rate_date'].max().date()}")
    print(f"Missing values (holidays/no quote): {rates['dtb3_pct'].isna().sum()}")
    print(f"Latest value: {valid['dtb3_pct'].iloc[-1]:.2f}% on {valid['rate_date'].iloc[-1].date()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
