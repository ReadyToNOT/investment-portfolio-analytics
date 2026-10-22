STAGE 7 KICKOFF: Investment Portfolio Analytics (Power BI model, measures and pages)

You're picking up a project already in progress. The Project instructions
(my working rules, the 8 stages, the five business questions) still apply in
full. Stages 1 to 6 are done and verified. This message gives you the current
state and a draft spec for Stage 7. Read all of it before building anything.

========================================================================
1. WHERE THINGS STAND
========================================================================
Repo: C:\Users\jacob\portfolio-analytics (Windows, PyCharm terminal = PowerShell)
Database: PostgreSQL, database portfolio_analytics, credentials in .env
Tools: Power BI Desktop (Windows), pgAdmin 4, PyCharm.
Python packages: pandas, sqlalchemy, psycopg2-binary, yfinance, python-dotenv.

Folder access: if this chat is linked to my computer (Claude desktop app),
read the project files yourself instead of asking me to paste them. You can't
click around Power BI for me, so for anything inside Power BI give me exact
click paths and the DAX/M code to paste. If you can't reach the folder, ask me
to paste files.

Full pipeline (each script exits 0 = all PASS, 1 = any FAIL). Run in this order:
  python src/ingest_prices.py       (only to refresh data)
  python src/ingest_rates.py        (only to refresh data)
  python src/check_raw_data.py      34 checks
  python src/load_staging.py
  python src/build_model.py         28 checks (M01-M28)
  python src/reconcile_holdings.py
  python src/build_analysis.py      22 checks (A01-A22)
  python src/build_backtest.py      22 checks (B01-B22)
Rule: build_model.py drops dim_* with CASCADE, which removes the Stage 5 and
Stage 6 foreign keys. After build_model.py, always re-run build_analysis.py
and then build_backtest.py.

Last full run (2026-10-21, all from running our code):
  build_model.py 28 passed, 0 failed; build_analysis.py 22/0; build_backtest.py 22/0.
  Row counts: dim_security 13, dim_date 1,416 (calendar days 2022-12-01 to
  2026-10-16), fact_prices 12,636, fact_transactions 23, fact_rates 1,011,
  vw_daily_holdings 8,904, fact_daily_portfolio 742, fact_daily_holding_returns
  8,892, fact_correlation 169, fact_drawdown_episodes 144,
  fact_risk_contribution 24, fact_holding_beta 12, analysis_summary 13,
  dim_strategy 5, fact_backtest_daily 3,710, fact_backtest_trades 781,
  fact_backtest_summary 164, fact_backtest_worst_drawdown 5.

Hand checks in docs/reconciliation.md:
  1 (AAPL holding value): [filled in: yes / no]
  2 (r_p on 2024-05-02):  [filled in: yes / no]
  3 (S2 rebalance on 2023-11-30): [filled in: yes / no]

Read before designing the model: docs/methodology.md (every Stage 5
definition), docs/backtest_rules.md (every Stage 6 rule),
sql/03_create_model.sql, sql/05_create_views.sql,
sql/08_create_analysis_tables.sql, sql/09_create_backtest_tables.sql.

========================================================================
2. THE SAMPLE PORTFOLIO AND THE RESULTS SO FAR (real numbers from our runs)
========================================================================
Fictional, educational. 12 holdings in 5 sectors: Technology (MSFT, AAPL),
Health Care (JNJ, UNH, XLV), Financials (JPM, XLF), Consumer Staples (PG, KO,
XLP), Energy (XOM, CVX). Target weights MSFT 0.12, AAPL 0.11, JPM 0.10,
XLF 0.10, XOM 0.09, JNJ 0.08, PG 0.08, CVX 0.08, KO 0.07, UNH 0.06, XLV 0.06,
XLP 0.05. Benchmark SPY. Portfolio period 2023-11-01 (base day) to 2026-10-16:
742 trading days, 741 return days. Opening value 99,455.49; total net
contributions 133,299.49 (23 trades on 7 dates, one AAPL sale).

Stage 5 anchors (time-weighted, full period):
  Portfolio total return 72.14 percent (0.721425297), SPY 87.25 percent (0.872481676)
  Annualized return: portfolio 20.29 percent, SPY 23.78 percent
  Annualized volatility: portfolio 11.11 percent, SPY 15.26 percent
  Sharpe: portfolio 1.43, SPY 1.27
  Max drawdown: portfolio -12.80 percent, SPY -18.76 percent
  Beta vs SPY (excess returns): 0.51
  Last 30-day volatility (vol30_p): 0.099202
  Exact values for all of these are in analysis_summary. The DAX measures
  must reproduce analysis_summary, not these rounded numbers.

Stage 6 headline (10 bp cost; ACTUAL and SPY have no costs):
  Line                      Total    Annual   Vol     Sharpe  MaxDD    Beta  Trades  Costs $  Cash
  Buy and hold              73.30    20.56    11.28   1.43    -13.07   0.52  0        99.90    0.0
  Monthly rebalance         76.86    21.40    11.05   1.53    -11.78   0.49  420      292.37   0.0
  50/200-day MA filter      36.54    11.17     8.43   0.80    -11.85   0.35  330      698.57   27.2
  Actual portfolio (ref)    72.14    20.29    11.11   1.43    -12.80   0.51
  SPY (ref)                 87.25    23.78    15.26   1.27    -18.76   1.00
  (percent except Sharpe, Beta, Trades = trades after the start, Costs in dollars,
  Cash = average cash weight in percent)
  Cost sensitivity, total return at 0 / 10 / 25 bp:
    Buy and hold 73.30 / 73.30 / 73.30 (the initial purchase cost is kept out of the index by design)
    Monthly rebalance 77.12 / 76.86 / 76.49
    50/200-day MA filter 37.30 / 36.54 / 35.42
  Interpretation guardrails: one roughly three-year path, no significance
  test, survivorship and hindsight in the holdings. Monthly rebalancing came
  out slightly ahead of buy-and-hold on this path. That is an observation,
  not a claim that it generally works, and nothing here is investment advice.

========================================================================
3. TABLES POWER BI WILL USE (all in PostgreSQL)
========================================================================
Dimensions
  dim_date       one row per CALENDAR day 2022-12-01 to 2026-10-16 (1,416 rows),
                 includes weekends, holidays and the warm-up period. Flags:
                 is_trading_day, is_month_end_trading_day, is_portfolio_period.
                 Also year, quarter, quarter_label, month_num, month_name,
                 year_month, month_start, iso_week, day_of_week, day_name.
                 Known quirk: is_month_end_trading_day is also TRUE on
                 2026-10-16 (last price date of an unfinished month). The
                 backtest corrects for it in Python. The Notes page must
                 mention it, and no visual may treat that date as a month-end.
  dim_security   ticker (PK), security_name, asset_class, sector, role
                 (HOLDING / BENCHMARK), target_weight (fraction, NULL for SPY), currency
  dim_strategy   strategy_code (PK), strategy_name, sort_order, is_reference, description

Stage 4 facts and view
  fact_prices (price_date, ticker, close_price, adj_close_price, dividend_per_share, ...)
  fact_transactions (transaction_id, trade_date, ticker, transaction_type, shares, trade_price, trade_value, net_contribution)
  fact_rates (rate_date, dtb3_discount_pct)
  vw_daily_holdings (price_date, ticker, shares_held, close_price, market_value, net_contribution, actual_weight)

Stage 5 facts (definitions: docs/methodology.md)
  fact_daily_portfolio, one row per portfolio day: price_date, is_base_day,
    market_value, net_contribution, r_p, r_spy, rf_rate_date, rf_annual,
    rf_daily, growth_prev, index_p, index_spy, cum_p, cum_spy, dd_p, dd_spy,
    vol30_p, vol90_p, vol30_spy, vol90_spy, beta90_p, hhi, effective_n,
    top5_share, max_abs_drift, max_drift_ticker
  fact_daily_holding_returns: price_date, ticker, r, w_prev, contrib, linked_contrib
  fact_correlation: ticker_a, ticker_b, correlation, sort_a, sort_b (169 rows)
  fact_drawdown_episodes: series (PORTFOLIO/SPY), episode_no, peak_date,
    trough_date, recovery_date, depth, days_to_trough, days_to_recover,
    days_peak_to_recovery, recovered, depth_rank
  fact_risk_contribution: method (HISTORICAL/CURRENT), ticker, weight_used,
    risk_contribution, window_start, window_end, return_days
  fact_holding_beta: ticker, beta_excess, beta_raw
  analysis_summary: metric_key, metric_name, portfolio_value, spy_value, unit,
    definition, period_start, period_end, sort_order

Stage 6 facts (rules: docs/backtest_rules.md)
  fact_backtest_daily: strategy_code, price_date, value, daily_return,
    index_value, cum_return, drawdown, cash_weight, cost_paid (10 bp only, 5 lines)
  fact_backtest_trades: strategy_code, price_date, ticker, side, units, price, traded_value, cost
  fact_backtest_summary (long): strategy_code, cost_bps, is_headline,
    metric_key, metric_name, value, unit, definition, sort_order
  fact_backtest_worst_drawdown: strategy_code, peak_date, trough_date,
    recovery_date, depth, days_to_trough, days_peak_to_recovery, recovered

Conventions: every return, weight and rate is a FRACTION (format as percent
in Power BI). Base day 2023-11-01 has NULL returns and index = 100.
Annualize with 252. Volatility uses the sample standard deviation (STDEV.S).

========================================================================
4. DECISIONS ALREADY MADE (don't reopen without telling me why)
========================================================================
- Results are computed in Python/SQL and loaded. DAX only aggregates and
  filters. No DAX re-implementation of returns or drawdowns from prices.
- Sharpe = (annualized return - average risk-free rate) / annualized volatility,
  average rf = (1 + mean rf_daily)^252 - 1. Beta uses excess returns.
- Backtest numbers come from fact_backtest_summary as stored. No DAX recompute.
- Sample portfolio, clearly labeled; disclaimer on the Notes page.

========================================================================
5. STAGE 7 DRAFT SPEC (challenge anything that's wrong, rule 8)
========================================================================
Step 0. Verify before relying on anything that can change (rule 4): how the
current Power BI Desktop connects to PostgreSQL (built-in connector, whether
it needs a separate driver, SSL/encryption setting for a local server), and
any DAX function behavior you use (for example PRODUCTX, WINDOW/OFFSET,
INDEX). Label anything from memory as unverified.

A. Connection and model
- Import mode (not DirectQuery). The data is small, and refresh = re-run the
  pipeline, then Refresh in Power BI. Credentials stay in Power BI's own store,
  never in the .pbix or the repo. Confirm this is true for the current version.
- Load the tables in section 3. Decide which Stage 4 tables are needed at all
  (keep lean: hide or skip what no visual uses).
- Set data types (dates as Date, fractions as Decimal number, booleans as True/False).
- Relationships: one-to-many, single direction, from dim_date[date_key],
  dim_security[ticker] and dim_strategy[strategy_code] to the facts. Tables
  with several date or ticker columns (fact_drawdown_episodes,
  fact_correlation, fact_risk_contribution, fact_backtest_worst_drawdown) get
  one active relationship and inactive ones only if a measure needs
  USERELATIONSHIP. Explain each choice. Propose whether fact_correlation
  needs two ticker roles (for example a second, disconnected security table)
  for the matrix.
- Mark dim_date as the date table. Sort month_name by month_num and
  strategy_name by sort_order. Report-level filter: is_portfolio_period = TRUE
  where needed (dim_date includes the warm-up period).
- Draw the model as a diagram (described in text) before I build it.

B. DAX measures (put them in one measures table; explain every formula in
plain language the first time; give display formats)
  Required by the project plan: annualized volatility, Sharpe ratio, max
  drawdown, excess return vs benchmark, weight drift. Also: latest market
  value, total return (compounded over the selected dates), annualized return,
  average risk-free rate, period return contribution by holding and sector
  (linked contributions divided by growth_prev on the first selected date,
  methodology.md section 9, so any date range reconciles exactly).
  Decide and explain how each measure behaves when a date range is selected:
  - total return should compound r_p over the selected return days
  - max drawdown for a sub-period cannot just be MIN(dd_p), because dd_p is
    measured from the all-time peak since the base day. Either compute it
    within the selection or label the KPI "since 2023-11-01" and lock it to the
    full period. Recommend one; keep it lean.
  - KPI cards must show the full-period values by default.

C. Measure validation (no invented results)
- A hidden "Checks" page: a table with each DAX measure at full period next
  to the stored analysis_summary value and the difference. Target: equal to
  1e-9 or better. Tell me exactly what numbers to expect. They must equal the
  analysis_summary values, which I can read in pgAdmin.
- At least one sub-period check: calendar year 2024 total return from the
  DAX measure vs a number I compute in pgAdmin with a SQL query you give me
  (product of (1 + r_p) over 2024 return days, minus 1; EXP(SUM(LN(...)))
  works in PostgreSQL).
- Weight drift check: drift for one holding on the last date by hand
  (actual_weight from vw_daily_holdings minus target_weight).

D. Pages (from the project plan)
  1 Executive summary: KPI cards (value, total return, excess return vs SPY,
    volatility, Sharpe, max drawdown) and portfolio vs SPY indexed to 100.
  2 Holdings and allocation: holdings table (weight, return, contribution),
    sector treemap, actual vs target weight bars (drift).
  3 Risk: rolling 30/90-day volatility lines, drawdown area chart,
    correlation matrix with conditional formatting, risk contribution
    (HISTORICAL vs CURRENT) by holding/sector.
  4 Attribution: waterfall of return contribution by holding or sector.
  5 Strategy backtest: index lines per strategy (legend from dim_strategy),
    metrics table (is_headline = TRUE), cost sensitivity table, worst
    drawdown table, and an on-page assumptions box (10 bp, trades at the close
    on adjusted prices, initial cost kept out of the index, MA rule checked
    monthly, survivorship bias).
  6 Notes: methodology summary, assumptions, data refresh date (latest
    price_date), the dim_date month-end quirk, disclaimer. A first draft is
    fine. Final polish is Stage 8.
  Every assumption must be labeled inside the dashboard (rule 6).
  Suggest a simple, consistent visual style (one accent color for the
  portfolio, a neutral color for SPY, the same strategy colors on every page).
  No full design system.

E. Files
- dashboard/portfolio_analytics.pbix.
- docs/dax_measures.md: every measure's name, DAX, plain-language
  explanation, format, and the value it must match.
- docs/powerbi_model.md: tables loaded, relationships (active/inactive),
  sort-by columns, filters, refresh steps.
- Check .gitignore: decide whether the .pbix should be committed (it contains
  only sample data) and confirm it holds no credentials.

========================================================================
6. HOW I WANT TO WORK THIS STAGE
========================================================================
- Plan first: reply with a short plan, the model diagram, the measure list
  with how each behaves under a date filter, and anything in this spec you
  think is wrong. Wait for my go-ahead.
- Then work in small steps I can check: connect and load, then
  relationships, then measures plus the Checks page, then pages 1 to 6. After
  each step tell me exactly what I should see and how to verify it, then
  wait.
- Give whole DAX measures and whole docs files (or write the .md files into my
  folder if you can reach it, and list every file you created or changed).
  Terminal commands ONE PER LINE (pasting several lines in PowerShell runs
  them as one block).
- Don't invent results. Any number in your messages must come from code or
  queries I've run, or be clearly labeled as expected or an assumption.
- I'm a beginner in DAX: explain row context vs filter context,
  CALCULATE, iterators (SUMX, PRODUCTX), and variables (VAR) the first time
  they appear.
- At the end: what to run/check, and a progress note for Stage 8 (polish,
  README with the top finding and its number first, screenshots, screen
  recording plan, GitHub, resume bullet, interview prep).
- Schedule: target Stage 7 done by Sunday Nov 8, Stage 8 by Sunday Nov 15,
  2026; about 6 to 8 hours a week. If something is expensive and adds
  little, say so and keep it lean.
