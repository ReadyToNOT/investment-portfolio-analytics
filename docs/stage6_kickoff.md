STAGE 6 KICKOFF: Investment Portfolio Analytics

You're picking up a project already in progress. The Project instructions
(my working rules, the 8 stages, the business questions) still apply in full.
Stages 1–5 are done and verified. This message gives you the current state
and a draft spec for Stage 6 (the optional backtest, business question 5:
"Would a simple rebalancing rule have improved results?"). Read all of it
before writing code.

========================================================================
1. WHERE THINGS STAND
========================================================================
Repo: C:\Users\jacob\portfolio-analytics (Windows, PyCharm terminal = PowerShell)
Database: PostgreSQL, database portfolio_analytics, credentials in .env
Packages: pandas, sqlalchemy, psycopg2-binary, yfinance, python-dotenv
(numpy comes with pandas). Don't add packages unless you truly need to;
if you do, tell me why.

Folder access: if this chat is linked to my computer (Claude desktop app),
you can read and write the project folder directly. Read the files below
yourself instead of asking me to paste them. If you can't reach the folder,
ask me to paste them.

Pipeline (each script exits 0 = all PASS, 1 = any FAIL), in this order:
  python src/ingest_prices.py       yfinance -> data/raw/prices_daily.csv, dividends.csv, splits.csv
  python src/ingest_rates.py        FRED API (DTB3) -> data/raw/fred_dtb3.csv
  python src/check_raw_data.py      34 raw-data checks
  python src/load_staging.py        CSVs -> stg_* tables (TRUNCATE + insert, one transaction)
  python src/build_model.py         sql/03, 04, 05 in one transaction, then sql/06 (28 checks)
  python src/reconcile_holdings.py  pandas recomputation vs the view (all rows match)
  python src/build_analysis.py      Stage 5: compute, load sql/08 tables in one transaction,
                                    read back, 22 checks (A01–A22)
Rule: build_model.py drops dim_* with CASCADE, which removes the Stage 5
foreign keys. Always re-run build_analysis.py after build_model.py.
Stage 6 adds one more script at the end with the same rule.

Shared helper modules (reuse them, don't copy them):
  src/config.py     PROJECT_ROOT, SECURITY_LOOKUP_CSV, TRANSACTIONS_CSV,
                    PORTFOLIO_START = 2023-11-01, DOWNLOAD_START = 2022-12-01,
                    WARMUP_TRADING_DAYS_NEEDED = 200, BENCHMARK_TICKER = "SPY",
                    RISK_FREE_SERIES_ID = "DTB3", NYSE_HOLIDAYS
  src/db.py         get_engine() -> SQLAlchemy engine built from .env
  src/raw_io.py     RAW_DIR, SQL_DIR, CSV paths, write_csv_atomic(), read_dtb3()
  src/build_model.py  read_sql(name) refuses any SQL file containing a percent
                    sign (psycopg2 treats it as a placeholder). Keep every SQL
                    file free of that character, comments included.
  src/analysis.py   load_inputs(engine), compute_all(inputs), plus helpers:
                    tbill_discount_to_bey(), annual_to_daily(), drawdown_series(),
                    drawdown_episodes(), build_summary(); constants
                    TRADING_DAYS_PER_YEAR = 252, VOL_WINDOWS, BETA_WINDOW, TBILL_DAYS = 91
  src/check_analysis.py  run_checks(inputs, tables) -> (id, name, expected, actual, passed)
  src/build_analysis.py  pattern to copy: compute -> one-transaction load ->
                    read back from PostgreSQL -> checks -> exit code
Read before writing code: config.py, analysis.py, build_analysis.py,
check_analysis.py, sql/08_create_analysis_tables.sql, docs/methodology.md.

Sample portfolio (fictional, educational):
  12 holdings in 5 sectors: Technology (MSFT, AAPL), Health Care (JNJ, UNH, XLV),
  Financials (JPM, XLF), Consumer Staples (PG, KO, XLP), Energy (XOM, CVX).
  Target weights (fractions in dim_security.target_weight): MSFT 0.12, AAPL 0.11,
  JPM 0.10, XLF 0.10, XOM 0.09, JNJ 0.08, PG 0.08, CVX 0.08, KO 0.07,
  UNH 0.06, XLV 0.06, XLP 0.05 (sum 1).
  Benchmark SPY (role = BENCHMARK, never traded).
  Actual portfolio: 23 trades on 7 trade dates (initial buys 2023-11-01, top-ups
  2024-05-01, 2024-11-01, 2025-05-01, 2025-11-03, 2026-05-01, one AAPL sale of
  20 shares on 2025-08-01). Trades at the close, no commissions, no cash, every
  buy funded with new money, sale proceeds withdrawn, no splits in the window.

Data window: prices 2022-12-01 to 2026-10-16 (972 trading days, 13 tickers).
Portfolio period 2023-11-01 to 2026-10-16 = 742 trading days (741 return days).
The pre-2023-11-01 history exists for the 200-day moving average warm-up.
DTB3 2022-12-01 to 2026-10-15.

Verified anchors (from running our code):
  Opening value on 2023-11-01 = 99,455.49
  Total net contributions = 133,299.49
  vw_daily_holdings = 8,904 rows
  fact_daily_portfolio = 742 rows, fact_daily_holding_returns = 8,892,
  fact_correlation = 169; build_analysis.py: 22 passed, 0 failed
  Stage 5 hand check (r_p on 2024-05-02, docs/reconciliation.md section 2):
  [I'll tell you whether I've filled it in]

========================================================================
2. WHAT STAGE 5 BUILT (read from these; don't recompute them)
========================================================================
fact_daily_portfolio (one row per portfolio trading day, base day included):
  market_value, net_contribution, r_p, r_spy, rf_rate_date, rf_annual, rf_daily,
  growth_prev, index_p, index_spy, cum_p, cum_spy, dd_p, dd_spy, vol30/vol90
  for portfolio and SPY, beta90_p, hhi, effective_n, top5_share,
  max_abs_drift, max_drift_ticker
fact_daily_holding_returns (holding x return day): r, w_prev, contrib, linked_contrib
fact_correlation, fact_drawdown_episodes, fact_risk_contribution
  (HISTORICAL and CURRENT), fact_holding_beta, analysis_summary
All definitions: docs/methodology.md.

========================================================================
3. DECISIONS ALREADY MADE (don't reopen without telling me why)
========================================================================
- Returns use adj_close_price (dividends included); market value uses close_price.
- Risk-free: DTB3 -> bond-equivalent yield 365d/(360 - 91d) -> daily
  (1 + BEY)^(1/252) - 1; day t uses the latest rate on or before t-1.
  rf_daily is already stored in fact_daily_portfolio; reuse it.
- Annualize with 252. Volatility = sample std (ddof 1) x sqrt(252).
  Sharpe = (annualized return - average rf annual) / annualized volatility.
  Max drawdown = min of index / running max - 1. Same definitions for every
  strategy, so backtest metrics compare directly with analysis_summary.
- Results computed in Python and loaded; DAX only aggregates and filters.
- Rebuild pattern: drop/create inside one transaction, re-runnable, PASS/FAIL
  checks on tables read back from PostgreSQL, exit code 0/1.

========================================================================
4. STAGE 6 DRAFT SPEC (challenge anything that's wrong, rule 8)
========================================================================
Step 0. Before writing any backtest code, write docs/backtest_rules.md:
every rule, parameter, cost and metric, fixed BEFORE seeing any results.
Show it to me first. No parameter may be changed after results are seen
(no tuning to the history). If something must change for a correctness
reason, log the change and the reason in the file.

Common setup (my proposal):
- Universe: the same 12 holdings, target weights from dim_security.
- Hypothetical capital: 100,000 at the close of 2023-11-01, invested at
  target weights, fractional shares allowed, no later contributions or
  withdrawals (so value-based and time-weighted returns are the same).
  The actual portfolio's TWR (fact_daily_portfolio) is shown alongside as a
  reference, with a note that it had real top-ups at non-target weights.
- Simulate with adj_close (total return, dividends reinvested in the same
  holding). State this as an assumption.
- Trades execute at the close. Trading cost: 10 basis points (0.10 percent)
  of traded value, every trade including the initial purchase, deducted from
  the portfolio. Report 0 and 25 basis points as a sensitivity table, but the
  headline uses 10 and is fixed in advance.
- Cash (only the MA rule holds any) earns rf_daily.
- Period: same as the analysis, 2023-11-01 to the last price date.

Strategies:
  S1 Buy-and-hold: buy at targets on day 1, never trade again.
  S2 Monthly rebalance: at the close of each month-end trading day
     (dim_date.is_month_end_trading_day) after the start, trade every holding
     back to its target weight. Costs on the traded amounts.
  S3 50/200-day moving-average rule, per holding: signal = 50-day simple MA
     of adj_close above the 200-day simple MA -> invested at its target
     weight; otherwise that slice sits in cash earning rf_daily.
     To avoid look-ahead, the signal computed at the close of day t is acted
     on at the close of day t+1. I'm unsure whether to evaluate the signal
     daily or only at month-ends (fewer trades, less whipsaw); recommend one
     and justify it before results exist. When re-entering, decide whether
     the slice returns to target weight of current total value, and say so.
  Reference: actual portfolio (from fact_daily_portfolio) and SPY.

Metrics per strategy (same definitions as Stage 5): total return, annualized
return, annualized volatility, Sharpe, max drawdown, worst drawdown episode
(peak, trough, recovery, days), beta vs SPY, number of trades, turnover
(traded value / average portfolio value, annualized), total costs paid,
average cash weight (S3).

Output tables (confirm or improve):
  fact_backtest_daily     strategy x trading day: value, daily return, index
                          (100 on the base day), cumulative, drawdown,
                          cash weight, cost paid that day
  fact_backtest_trades    one row per trade: strategy, date, ticker, side,
                          shares, price, traded value, cost
  fact_backtest_summary   strategy x metric, at the headline cost, plus the
                          cost sensitivity rows (0 / 10 / 25 basis points)
  strategy is TEXT with a CHECK constraint (or a tiny dim_strategy table if
  you think Power BI needs it); dates and tickers are foreign keys.

Files I expect (whole files, paths relative to the project folder, every new
concept explained in plain language):
  docs/backtest_rules.md
  sql/09_create_backtest_tables.sql
  src/backtest.py           (simulation, pure functions: DataFrames in and out)
  src/check_backtest.py     (PASS/FAIL checks)
  src/build_backtest.py     (run command, same pattern as build_analysis.py)

========================================================================
5. VALIDATION I EXPECT (at minimum)
========================================================================
- Index = 100 on 2023-11-01 for every strategy; value = sum of positions
  (+ cash) every day (1e-6 dollars).
- Buy-and-hold at 0 cost: daily return = sum of previous-close weights x
  holding returns (1e-12), reusing the Stage 5 logic.
- Monthly rebalance: right after each rebalance, weights = targets (1e-9);
  between rebalances, share counts don't change.
- Costs: total cost = cost rate x total traded value (1e-9); at 0 cost the
  strategies' results differ only because of trading decisions.
- MA rule: no look-ahead (a test that shifts the signal and confirms it was
  computed only from data up to t-1 on each execution day); the first
  signal date has a full 200 days of history; cash weight in [0, 1].
- Summary metrics recomputed from the daily table agree (1e-12).
- Drawdown <= 0 everywhere; no NULL values where they shouldn't be.
- Row counts: fact_backtest_daily = strategies x 742.
- One hand check I do myself: the S2 rebalance trades on the first month-end
  (2023-11-30) from the CSVs with a calculator, added to docs/reconciliation.md.

========================================================================
6. HOW I WANT TO WORK THIS STAGE
========================================================================
- Plan first: reply with a short plan, the backtest_rules.md draft and
  anything in this spec you think is wrong. Wait for my go-ahead before
  writing the backtest code.
- Then give whole files (or write them into my folder if you can reach it,
  and list every file you created or changed). Terminal commands ONE PER
  LINE (pasting several lines in PowerShell runs them as one block).
- At the end, tell me exactly what to run, what output to expect and how to
  check it, and give me a progress note for the next chat (Stage 7, Power BI).
- Don't invent results. Any number in your messages must come from code I've
  run, or be clearly labelled as an expected value or an assumption.
- Survivorship bias and hindsight in the choice of holdings are limitations
  to state, not fix. No investment advice; this is a sample portfolio.
- Schedule: Stages 6–8 between Nov 2 and Nov 15, 2026; about 6–8 hrs/week.
  Stage 6 is optional, so keep it lean: if something is expensive and adds
  little, say so.
