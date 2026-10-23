# data/raw

Raw downloads, saved exactly as received so every run can be traced and repeated.

| File | Source | In this repository? |
|---|---|---|
| `prices_daily.csv` | Yahoo Finance via yfinance | No, kept local only |
| `dividends.csv` | Yahoo Finance via yfinance | No, kept local only |
| `splits.csv` | Yahoo Finance via yfinance | No, kept local only |
| `fred_dtb3.csv` | FRED series DTB3 (3-month Treasury bill), via the FRED API | Yes |
| `download_log.csv` | Written by the ingest scripts: what was downloaded and when | Yes |

**Why the Yahoo files are missing:** Yahoo's terms of service restrict redistributing its
data, and yfinance states that the Yahoo Finance API is intended for personal use only.
To create them, run from the project folder:

    python src/ingest_prices.py

A new download will end on a later date and may differ slightly for older days, because
yfinance restates adjusted prices when new dividends are paid. The published results in
the README use data through 2026-10-16.
