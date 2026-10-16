"""
src/validate_inputs.py
Checks the two hand-made input files before any data is downloaded:
    data/processed/security_lookup.csv
    data/processed/transactions.csv

Each check prints PASS or FAIL with a short reason. The script exits with
code 0 if everything passes and code 1 if anything fails, so later stages
(or a pipeline) can stop early on bad inputs.

Run from the project folder:   python src/validate_inputs.py
"""
import sys
from datetime import date, timedelta

import pandas as pd

import config  # src/config.py (same folder, so a plain import works)

results = []  # list of (passed: bool, check name, detail text)


def check(passed, name, detail=""):
    """Record and print one check result."""
    results.append((passed, name, detail))
    label = "PASS" if passed else "FAIL"
    line = f"[{label}] {name}"
    if detail:
        line += f" -- {detail}"
    print(line)


def is_trading_day(d):
    """True if d is a weekday and not an NYSE holiday."""
    return d.weekday() < 5 and d not in config.NYSE_HOLIDAYS


def count_trading_days(start, end):
    """Trading days from start (inclusive) to end (exclusive)."""
    n, d = 0, start
    while d < end:
        if is_trading_day(d):
            n += 1
        d += timedelta(days=1)
    return n


# ---------------------------------------------------------------------------
# 1. Load both files. dtype=str reads every cell as text first, so nothing is
#    silently converted; we convert columns ourselves and catch bad values.
# ---------------------------------------------------------------------------
print("=" * 70)
print("Validating Stage 2 inputs (SAMPLE portfolio - not investment advice)")
print("=" * 70)

try:
    lookup = pd.read_csv(config.SECURITY_LOOKUP_CSV, dtype=str, keep_default_na=False)
    tx = pd.read_csv(config.TRANSACTIONS_CSV, dtype=str, keep_default_na=False)
except FileNotFoundError as e:
    print(f"[FAIL] Could not open input file: {e}")
    sys.exit(1)

# Trim stray spaces from every text cell (a common typing mistake).
lookup = lookup.apply(lambda col: col.str.strip())
tx = tx.apply(lambda col: col.str.strip())

# ---------------------------------------------------------------------------
# 2. Security lookup checks
# ---------------------------------------------------------------------------
print("\n-- security_lookup.csv --")

lookup_cols = ["ticker", "security_name", "asset_class", "sector", "role",
               "target_weight_pct", "currency"]
missing = [c for c in lookup_cols if c not in lookup.columns]
check(not missing, "Lookup has all required columns",
      f"missing: {missing}" if missing else "")
if missing:
    sys.exit(1)

dupes = lookup.loc[lookup["ticker"].duplicated(), "ticker"].tolist()
check(not dupes, "Lookup tickers are unique", f"duplicates: {dupes}" if dupes else "")

blank = [c for c in ["ticker", "security_name", "asset_class", "sector", "role", "currency"]
         if (lookup[c] == "").any()]
check(not blank, "Name, sector, asset class, role and currency are filled in",
      f"blank cells in: {blank}" if blank else "")

bad_class = sorted(set(lookup["asset_class"]) - {"Stock", "ETF"})
check(not bad_class, "asset_class is Stock or ETF", f"bad values: {bad_class}" if bad_class else "")

bad_role = sorted(set(lookup["role"]) - {"HOLDING", "BENCHMARK"})
check(not bad_role, "role is HOLDING or BENCHMARK", f"bad values: {bad_role}" if bad_role else "")

bench = lookup.loc[lookup["role"] == "BENCHMARK", "ticker"].tolist()
check(bench == [config.BENCHMARK_TICKER],
      f"Exactly one benchmark and it is {config.BENCHMARK_TICKER}", f"found: {bench}")

bench_weight = lookup.loc[lookup["role"] == "BENCHMARK", "target_weight_pct"]
check((bench_weight == "").all(), "Benchmark has no target weight (it is not a holding)")

holdings = lookup[lookup["role"] == "HOLDING"].copy()
holdings["target_weight_pct"] = pd.to_numeric(holdings["target_weight_pct"], errors="coerce")
bad_w = holdings.loc[holdings["target_weight_pct"].isna() | (holdings["target_weight_pct"] <= 0),
                     "ticker"].tolist()
check(not bad_w, "Every holding has a positive numeric target weight",
      f"problem tickers: {bad_w}" if bad_w else "")

total_w = holdings["target_weight_pct"].sum()
check(abs(total_w - 100) < 1e-6, "Holding target weights sum to 100%", f"sum = {total_w:g}%")

n_hold = len(holdings)
check(10 <= n_hold <= 15, "Holding count is between 10 and 15", f"{n_hold} holdings")

n_sect = holdings["sector"].nunique()
check(4 <= n_sect <= 5, "Holdings span 4 or 5 sectors", f"{n_sect} sectors")

n_etf = int((holdings["asset_class"] == "ETF").sum())
check(n_etf >= 2, "Portfolio includes at least 2 ETFs", f"{n_etf} ETFs")

# ---------------------------------------------------------------------------
# 3. Transactions checks
# ---------------------------------------------------------------------------
print("\n-- transactions.csv --")

tx_cols = ["transaction_id", "trade_date", "ticker", "transaction_type", "shares"]
missing = [c for c in tx_cols if c not in tx.columns]
check(not missing, "Transactions have all required columns",
      f"missing: {missing}" if missing else "")
if missing:
    sys.exit(1)

dupes = tx.loc[tx["transaction_id"].duplicated(), "transaction_id"].tolist()
check(not dupes, "transaction_id values are unique", f"duplicates: {dupes}" if dupes else "")

# Dates: must be real calendar dates in YYYY-MM-DD form.
tx["trade_date_parsed"] = pd.to_datetime(tx["trade_date"], format="%Y-%m-%d", errors="coerce")
bad_dates = tx.loc[tx["trade_date_parsed"].isna(), "transaction_id"].tolist()
check(not bad_dates, "All trade dates parse as YYYY-MM-DD",
      f"bad rows: {bad_dates}" if bad_dates else "")

ok_dates = tx.dropna(subset=["trade_date_parsed"]).copy()
ok_dates["d"] = ok_dates["trade_date_parsed"].dt.date

weekend = ok_dates.loc[ok_dates["d"].map(lambda d: d.weekday() >= 5), "transaction_id"].tolist()
check(not weekend, "No trade falls on a weekend", f"rows: {weekend}" if weekend else "")

uncovered = ok_dates.loc[~ok_dates["d"].map(lambda d: d.year in config.HOLIDAY_YEARS_COVERED),
                         "transaction_id"].tolist()
holiday = ok_dates.loc[ok_dates["d"].isin(config.NYSE_HOLIDAYS), "transaction_id"].tolist()
check(not holiday and not uncovered, "No trade falls on an NYSE holiday",
      (f"holiday rows: {holiday} " if holiday else "")
      + (f"years not in holiday list: {uncovered}" if uncovered else ""))

if not ok_dates.empty:
    first, last = ok_dates["d"].min(), ok_dates["d"].max()
    check(first == config.PORTFOLIO_START, "First trade date equals PORTFOLIO_START",
          f"first = {first}, config = {config.PORTFOLIO_START}")
    check(last <= date.today(), "No trade is dated in the future", f"last = {last}")

unknown = sorted(set(tx["ticker"]) - set(holdings["ticker"]))
check(not unknown, "Every traded ticker is a HOLDING in the lookup",
      f"unknown or benchmark tickers: {unknown}" if unknown else "")

never_bought = sorted(set(holdings["ticker"]) - set(
    tx.loc[(tx["transaction_type"] == "BUY") & (tx["trade_date"] == str(config.PORTFOLIO_START)),
           "ticker"]))
check(not never_bought, "Every holding is bought on the start date",
      f"missing initial buy: {never_bought}" if never_bought else "")

bad_type = sorted(set(tx["transaction_type"]) - {"BUY", "SELL"})
check(not bad_type, "transaction_type is BUY or SELL", f"bad values: {bad_type}" if bad_type else "")

tx["shares_num"] = pd.to_numeric(tx["shares"], errors="coerce")
bad_shares = tx.loc[tx["shares_num"].isna() | (tx["shares_num"] <= 0), "transaction_id"].tolist()
check(not bad_shares, "Shares are positive numbers", f"bad rows: {bad_shares}" if bad_shares else "")

# Running position: BUY adds shares, SELL subtracts. Sort by date (then ID so
# same-day trades keep file order) and keep a running total per ticker.
pos = tx.dropna(subset=["trade_date_parsed", "shares_num"]).copy()
pos["signed"] = pos["shares_num"].where(pos["transaction_type"] == "BUY", -pos["shares_num"])
pos = pos.sort_values(["trade_date_parsed", "transaction_id"])
pos["running"] = pos.groupby("ticker")["signed"].cumsum()
negative = pos.loc[pos["running"] < 0, "transaction_id"].tolist()
check(not negative, "No holding is ever sold below zero shares",
      f"rows that go negative: {negative}" if negative else "")

# ---------------------------------------------------------------------------
# 4. Date-window check for the backtest warm-up (flag 1 from Stage 1).
# ---------------------------------------------------------------------------
print("\n-- date window --")
warm = count_trading_days(config.DOWNLOAD_START, config.PORTFOLIO_START)
check(warm >= config.WARMUP_TRADING_DAYS_NEEDED,
      f"At least {config.WARMUP_TRADING_DAYS_NEEDED} trading days of warm-up before the first buy",
      f"{warm} trading days from {config.DOWNLOAD_START} to {config.PORTFOLIO_START}")

# ---------------------------------------------------------------------------
# 5. Summary
# ---------------------------------------------------------------------------
n_fail = sum(1 for passed, _, _ in results if not passed)
print("\n" + "=" * 70)
print(f"{len(results) - n_fail} passed, {n_fail} failed")

# Ending position per holding, as a quick visual check.
if not pos.empty:
    final = pos.groupby("ticker")["signed"].sum().astype(int)
    print("\nShares held after the last transaction:")
    print(final.to_string())

sys.exit(1 if n_fail else 0)
