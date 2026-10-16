"""
src/config.py
Project-wide settings in one place, so every script uses the same dates,
tickers and file paths. Change a value here, not inside individual scripts.
"""
from datetime import date
from pathlib import Path

# Project root = the folder above src/ (works no matter where you run from).
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Input files designed in Stage 2.
SECURITY_LOOKUP_CSV = PROJECT_ROOT / "data" / "processed" / "security_lookup.csv"
TRANSACTIONS_CSV = PROJECT_ROOT / "data" / "processed" / "transactions.csv"

# Date window.
# PORTFOLIO_START: first buy date of the sample portfolio (a Wednesday, NYSE open).
# DOWNLOAD_START: earlier date for price downloads, so the 200-day moving-average
#                 backtest rule has a full 200 trading days of history before
#                 PORTFOLIO_START (about 11 months of warm-up).
PORTFOLIO_START = date(2023, 11, 1)
DOWNLOAD_START = date(2022, 12, 1)
WARMUP_TRADING_DAYS_NEEDED = 200

# Benchmark and risk-free rate.
BENCHMARK_TICKER = "SPY"
# FRED series DTB3 = 3-Month Treasury Bill Secondary Market Rate, Discount Basis,
# daily, in percent (verified on fred.stlouisfed.org, Oct 2026).
RISK_FREE_SERIES_ID = "DTB3"

# NYSE full-day closures (weekdays the market is shut).
# 2026: verified against NYSE's published calendar (Oct 2026).
# 2022-2025: typed from memory (UNVERIFIED); Stage 3 cross-checks every date
#            against the actual trading days in the downloaded price data.
NYSE_HOLIDAYS = {
    # 2022 (only the part inside the download window matters)
    date(2022, 12, 26),
    # 2023
    date(2023, 1, 2), date(2023, 1, 16), date(2023, 2, 20), date(2023, 4, 7),
    date(2023, 5, 29), date(2023, 6, 19), date(2023, 7, 4), date(2023, 9, 4),
    date(2023, 11, 23), date(2023, 12, 25),
    # 2024
    date(2024, 1, 1), date(2024, 1, 15), date(2024, 2, 19), date(2024, 3, 29),
    date(2024, 5, 27), date(2024, 6, 19), date(2024, 7, 4), date(2024, 9, 2),
    date(2024, 11, 28), date(2024, 12, 25),
    # 2025 (Jan 9 = National Day of Mourning for President Carter)
    date(2025, 1, 1), date(2025, 1, 9), date(2025, 1, 20), date(2025, 2, 17),
    date(2025, 4, 18), date(2025, 5, 26), date(2025, 6, 19), date(2025, 7, 4),
    date(2025, 9, 1), date(2025, 11, 27), date(2025, 12, 25),
    # 2026 (verified)
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
}
# Years the holiday list fully covers; dates outside this can't be checked.
HOLIDAY_YEARS_COVERED = {2023, 2024, 2025, 2026}
