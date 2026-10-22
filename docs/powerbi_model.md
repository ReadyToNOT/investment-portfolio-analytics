# Power BI model (Stage 7)

File: `dashboard/portfolio_analytics.pbix` (Power BI Desktop, Import mode).
Data source: local PostgreSQL, server `localhost`, database `portfolio_analytics`.
Sample portfolio, educational project, not investment advice.

## 1. Connection

- Connector: Get data > PostgreSQL database (built in; Power BI Desktop has bundled
  Npgsql 4.0.17 since the October 2024 release, so no driver install is needed).
- Mode: Import. The data is small (largest table 8,904 rows), and a refresh means
  re-running the Python pipeline, then clicking Refresh in Power BI.
- Encryption: the local server has no SSL, so Power BI shows an "unencrypted
  connection" warning once; OK connects without encryption (fine for localhost).
- Credentials: entered once in Power BI's login window (Database tab, user and
  password from `.env`). They are stored by Power BI on this PC, not in the .pbix
  or the repository. The .pbix does contain the server and database names.
- Options set before loading (File > Options and settings > Options):
  - Global > Data Load: Auto date/time for new files OFF.
  - Current file > Data Load: Import relationships from data sources on first
    load OFF; Autodetect new relationships OFF; Auto date/time OFF.
  - Reason: the database has foreign keys on every date column, which would have
    created unwanted relationships; dim_date replaces the hidden auto date tables.

## 2. Tables loaded (14) and tables skipped

Query names were renamed from `public xxx` to `xxx` in Power Query Editor.
No data types needed changing (no Fixed decimal, no Date/Time).

| Table | Rows (2026-10-21) | Used for |
|---|---|---|
| dim_date | 1,416 | Calendar, date slicer, chart axes |
| dim_security | 13 | Ticker, name, sector, target weight |
| dim_strategy | 5 | Strategy names, line order, legend |
| vw_daily_holdings | 8,904 | Weights, drift, market value per holding |
| fact_daily_portfolio | 742 | Portfolio and SPY returns, index, drawdown, rolling vol, concentration |
| fact_daily_holding_returns | 8,892 | Holding returns and contributions |
| fact_correlation | 169 | Correlation matrix |
| fact_drawdown_episodes | 144 | Worst drawdowns table |
| fact_risk_contribution | 24 | Risk share by holding/sector |
| fact_holding_beta | 12 | Holding betas (loaded; available for tooltips) |
| analysis_summary | 13 | Reference values for the Checks page, beta card |
| fact_backtest_daily | 3,710 | Strategy growth lines |
| fact_backtest_summary | 164 | Backtest metrics and cost sensitivity |
| fact_backtest_worst_drawdown | 5 | Worst drawdown per strategy |

Skipped (no visual uses them): fact_prices, fact_transactions, fact_rates,
fact_backtest_trades, and all stg_* staging tables. rf and net contributions are
already in fact_daily_portfolio; trade counts and costs are in fact_backtest_summary.

Plus `_Measures`: an empty table (Enter data) that holds every DAX measure
(see `docs/dax_measures.md`).

## 3. Relationships (11, all one-to-many, single direction, active)

| # | One side | Many side |
|---|---|---|
| 1 | dim_date[date_key] | fact_daily_portfolio[price_date] |
| 2 | dim_date[date_key] | fact_daily_holding_returns[price_date] |
| 3 | dim_date[date_key] | vw_daily_holdings[price_date] |
| 4 | dim_date[date_key] | fact_backtest_daily[price_date] |
| 5 | dim_security[ticker] | fact_daily_holding_returns[ticker] |
| 6 | dim_security[ticker] | vw_daily_holdings[ticker] |
| 7 | dim_security[ticker] | fact_risk_contribution[ticker] |
| 8 | dim_security[ticker] | fact_holding_beta[ticker] |
| 9 | dim_strategy[strategy_code] | fact_backtest_daily[strategy_code] |
| 10 | dim_strategy[strategy_code] | fact_backtest_summary[strategy_code] |
| 11 | dim_strategy[strategy_code] | fact_backtest_worst_drawdown[strategy_code] |

Deliberately NOT related (decision 3 of the Stage 7 plan):
- fact_correlation: full-period table; the matrix uses its own ticker_a / ticker_b
  columns, so no second (role-playing) security table is needed.
- fact_drawdown_episodes, analysis_summary: full-period tables that must not
  change with the date slicer.
- Date columns other than price_date (peak/trough/recovery dates, window
  start/end, rf_rate_date) and fact_daily_portfolio[max_drift_ticker]: display only.
No inactive relationships exist, because no measure needs USERELATIONSHIP.

## 4. Date table, sort orders, summarization

- dim_date marked as the date table on date_key (Power BI validated: unique, no gaps).
- Sort by column: dim_date month_name by month_num; dim_date day_name by
  day_of_week; dim_strategy strategy_name by sort_order; fact_correlation ticker_a
  by sort_a and ticker_b by sort_b; fact_backtest_summary metric_name by sort_order.
- Don't summarize: dim_date year, quarter, month_num, iso_week, day_of_week;
  dim_strategy sort_order; fact_correlation sort_a, sort_b; fact_drawdown_episodes
  episode_no, depth_rank; fact_backtest_summary cost_bps, sort_order;
  analysis_summary sort_order.
- Column formats: fact_daily_portfolio vol30_p, vol90_p, vol90_spy, dd_p, dd_spy
  percent; drawdown depths percent; risk_contribution percent; correlation 2 decimals;
  peak/trough/recovery dates short date.

## 5. Filters

- Report level (all pages): dim_date[is_portfolio_period] = TRUE (hides the
  warm-up history from 2022-12-01) and dim_security[role] = HOLDING (keeps SPY out
  of holdings visuals; SPY's own numbers come from fact_daily_portfolio and
  fact_backtest_* columns, which this filter does not touch).
- Date slicer (dim_date[date_key], Between), synced on Executive Summary,
  Holdings & Allocation, Risk and Attribution. Saved at the full range so KPI cards
  open on the full period. Not on Strategy Backtest (stored full-period metrics).
- Visual-level: worst drawdowns depth_rank <= 5; backtest headline matrix
  is_headline = TRUE and 9 chosen metrics; cost matrix metric = Total return and
  is_reference = FALSE.

## 6. Pages

1. Executive Summary: KPI cards (portfolio and SPY), growth of 100 rebased to the
   first selected day, assumptions box.
2. Holdings & Allocation: concentration cards (effective holdings, top-5 share,
   largest drift and ticker), holdings table with data bars, sector treemap,
   actual vs target weight bars.
3. Risk: beta card, rolling 30/90-day volatility, drawdown area chart, 5 worst
   drawdowns per series, correlation matrix, risk share by sector (historical vs current).
4. Attribution: contribution waterfalls by holding and by sector, return share vs
   risk share table.
5. Strategy Backtest: growth lines per strategy, headline metrics, cost
   sensitivity, worst drawdown per strategy, rules, assumptions.
6. Notes: methodology, data sources, assumptions, quirks, limitations, data-through
   date, disclaimer.
7. Checks (hidden in Stage 8): DAX vs analysis_summary, 2024 and contribution checks.

Colors: Portfolio/Actual #1F6FB2, SPY #9E9E9E, Buy and hold #7B4FA0,
Monthly rebalance #E07B39, 50/200-day MA filter #2E9E6A.

## 7. Refresh steps

Run in PowerShell from the project folder, one line at a time:

```
python src/ingest_prices.py
python src/ingest_rates.py
python src/check_raw_data.py
python src/load_staging.py
python src/build_model.py
python src/reconcile_holdings.py
python src/build_analysis.py
python src/build_backtest.py
```

Each check script must exit with all PASS. Then in Power BI: Home > Refresh,
open the Checks page and confirm every row says PASS, and check the Notes page
"Data through" date. Note: a fresh yfinance download can restate older adj_close
values, so numbers may move slightly after a refresh.
