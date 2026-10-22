-- sql/09_create_backtest_tables.sql
-- Stage 6: tables that hold the strategy backtest computed in Python
-- (src/backtest.py). Every rule behind these numbers is in docs/backtest_rules.md.
--
-- Run by src/build_backtest.py, inside ONE transaction together with the
-- inserts, so a failed run leaves the previous results untouched.
-- Every table is dropped and re-created on each run, so re-runs never
-- duplicate rows.
--
-- Conventions (same as sql/08):
-- * Returns, weights and drawdowns are FRACTIONS (0.0123 = 1.23 in percent terms).
-- * Dates reference dim_date and tickers reference dim_security (foreign keys).
-- * sql/03_create_model.sql drops dim_date and dim_security with CASCADE,
--   which also removes these foreign keys. Always re-run build_analysis.py and
--   then build_backtest.py after build_model.py.
-- * Keep this file free of the percent sign: the database driver treats it
--   as a placeholder (build_model.read_sql refuses such files).

DROP TABLE IF EXISTS
    fact_backtest_daily,
    fact_backtest_trades,
    fact_backtest_summary,
    fact_backtest_worst_drawdown,
    dim_strategy
CASCADE;

-- ---------------------------------------------------------------------------
-- dim_strategy: the three simulated strategies plus the two references.
-- A small dimension instead of a CHECK constraint because Power BI needs the
-- display name and the line order anyway (legend, slicer, sort by column).
-- ---------------------------------------------------------------------------
CREATE TABLE dim_strategy (
    strategy_code  TEXT PRIMARY KEY,
    strategy_name  TEXT     NOT NULL,
    sort_order     SMALLINT NOT NULL UNIQUE,
    is_reference   BOOLEAN  NOT NULL,   -- TRUE = ACTUAL and SPY (not simulated, no costs)
    description    TEXT     NOT NULL
);

-- ---------------------------------------------------------------------------
-- fact_backtest_daily: one row per strategy per portfolio trading day,
-- at the HEADLINE cost (10 basis points). 5 x 742 rows.
-- NULLs by design: daily_return on the base day; value for SPY;
-- cash_weight and cost_paid for ACTUAL and SPY.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_backtest_daily (
    strategy_code  TEXT NOT NULL REFERENCES dim_strategy (strategy_code),
    price_date     DATE NOT NULL REFERENCES dim_date (date_key),
    value          DOUBLE PRECISION,             -- dollars after that day's trades and costs
    daily_return   DOUBLE PRECISION,             -- value / previous value - 1
    index_value    DOUBLE PRECISION NOT NULL CHECK (index_value > 0),   -- 100 on the base day
    cum_return     DOUBLE PRECISION NOT NULL,
    drawdown       DOUBLE PRECISION NOT NULL CHECK (drawdown <= 0),
    cash_weight    DOUBLE PRECISION CHECK (cash_weight BETWEEN 0 AND 1),
    cost_paid      DOUBLE PRECISION CHECK (cost_paid >= 0),           -- trading cost paid that day
    PRIMARY KEY (strategy_code, price_date)
);

-- ---------------------------------------------------------------------------
-- fact_backtest_trades: one row per trade at the headline cost (S1 to S3).
-- units are "adjusted units" (value / adj_close), NOT real share counts.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_backtest_trades (
    strategy_code  TEXT NOT NULL REFERENCES dim_strategy (strategy_code),
    price_date     DATE NOT NULL REFERENCES dim_date (date_key),
    ticker         TEXT NOT NULL REFERENCES dim_security (ticker),
    side           TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    units          DOUBLE PRECISION NOT NULL CHECK (units > 0),
    price          DOUBLE PRECISION NOT NULL CHECK (price > 0),          -- adj_close that day
    traded_value   DOUBLE PRECISION NOT NULL CHECK (traded_value > 0),   -- units x price
    cost           DOUBLE PRECISION NOT NULL CHECK (cost >= 0),          -- cost rate x traded_value
    PRIMARY KEY (strategy_code, price_date, ticker)
);

-- ---------------------------------------------------------------------------
-- fact_backtest_summary: long format, one row per strategy, cost level and
-- metric. Filter is_headline = TRUE for the main table (S1 to S3 at 10 bp,
-- ACTUAL and SPY once each with cost_bps = 0); the 0 and 25 bp rows are the
-- cost sensitivity.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_backtest_summary (
    strategy_code  TEXT     NOT NULL REFERENCES dim_strategy (strategy_code),
    cost_bps       SMALLINT NOT NULL CHECK (cost_bps IN (0, 10, 25)),
    is_headline    BOOLEAN  NOT NULL,
    metric_key     TEXT     NOT NULL,
    metric_name    TEXT     NOT NULL,
    value          DOUBLE PRECISION NOT NULL,
    unit           TEXT     NOT NULL,   -- fraction, ratio, USD, count, days
    definition     TEXT     NOT NULL,
    sort_order     SMALLINT NOT NULL,
    PRIMARY KEY (strategy_code, cost_bps, metric_key)
);

-- ---------------------------------------------------------------------------
-- fact_backtest_worst_drawdown: the deepest drawdown of each line at the
-- headline cost (same episode rules as fact_drawdown_episodes).
-- recovery_date and days_peak_to_recovery are NULL if not yet recovered.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_backtest_worst_drawdown (
    strategy_code          TEXT PRIMARY KEY REFERENCES dim_strategy (strategy_code),
    peak_date              DATE NOT NULL REFERENCES dim_date (date_key),
    trough_date            DATE NOT NULL REFERENCES dim_date (date_key),
    recovery_date          DATE REFERENCES dim_date (date_key),
    depth                  DOUBLE PRECISION NOT NULL CHECK (depth < 0),
    days_to_trough         INTEGER NOT NULL,   -- trading days, peak to trough
    days_peak_to_recovery  INTEGER,            -- trading days, peak to recovery
    recovered              BOOLEAN NOT NULL
);
