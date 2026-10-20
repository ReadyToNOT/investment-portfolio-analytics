-- sql/08_create_analysis_tables.sql
-- Stage 5: tables that hold the analysis results computed in Python
-- (src/analysis.py). Definitions of every column are in docs/methodology.md.
--
-- Run by src/build_analysis.py, inside ONE transaction together with the
-- inserts, so a failed run leaves the previous results untouched.
--
-- Every table is dropped and re-created on each run (same pattern as
-- sql/03_create_model.sql), so a re-run never duplicates rows and a column
-- change here takes effect on the next run.
--
-- Conventions:
-- * Returns, weights, rates and drawdowns are FRACTIONS (0.0123 = 1.23 percent).
-- * Every date column REFERENCES dim_date and every ticker column REFERENCES
--   dim_security (foreign keys), so PostgreSQL refuses a date or ticker the
--   model does not know.
-- * Important: sql/03_create_model.sql drops dim_date and dim_security with
--   CASCADE, which also removes these foreign keys. So after every run of
--   build_model.py, run build_analysis.py again (it re-creates everything).
-- * DOUBLE PRECISION is a 64-bit floating point number, the same type pandas
--   uses, so values round-trip without rounding.

DROP TABLE IF EXISTS
    fact_daily_portfolio,
    fact_daily_holding_returns,
    fact_correlation,
    fact_drawdown_episodes,
    fact_risk_contribution,
    fact_holding_beta,
    analysis_summary
CASCADE;

-- ---------------------------------------------------------------------------
-- fact_daily_portfolio: one row per portfolio trading day, base day included.
-- On the base day (2023-11-01) there is no return, so every return-based
-- column is NULL there, while the index columns are 100.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_daily_portfolio (
    price_date        DATE PRIMARY KEY REFERENCES dim_date (date_key),
    is_base_day       BOOLEAN          NOT NULL,
    market_value      DOUBLE PRECISION NOT NULL,  -- after that day's trades, unadjusted close
    net_contribution  DOUBLE PRECISION NOT NULL,  -- money added (+) or withdrawn (-) that day
    r_p               DOUBLE PRECISION,           -- portfolio time-weighted daily return
    r_spy             DOUBLE PRECISION,           -- SPY daily return
    rf_rate_date      DATE REFERENCES dim_date (date_key),  -- DTB3 date the rate came from
    rf_annual         DOUBLE PRECISION,           -- bond-equivalent yield
    rf_daily          DOUBLE PRECISION,           -- per trading day
    growth_prev       DOUBLE PRECISION,           -- G(t-1): growth of 1 up to the previous close
    index_p           DOUBLE PRECISION NOT NULL,  -- 100 on the base day
    index_spy         DOUBLE PRECISION NOT NULL,
    cum_p             DOUBLE PRECISION NOT NULL,
    cum_spy           DOUBLE PRECISION NOT NULL,
    dd_p              DOUBLE PRECISION NOT NULL CHECK (dd_p <= 0),
    dd_spy            DOUBLE PRECISION NOT NULL CHECK (dd_spy <= 0),
    vol30_p           DOUBLE PRECISION,           -- NULL until the window is full
    vol90_p           DOUBLE PRECISION,
    vol30_spy         DOUBLE PRECISION,
    vol90_spy         DOUBLE PRECISION,
    beta90_p          DOUBLE PRECISION,
    hhi               DOUBLE PRECISION NOT NULL,
    effective_n       DOUBLE PRECISION NOT NULL,
    top5_share        DOUBLE PRECISION NOT NULL,
    max_abs_drift     DOUBLE PRECISION NOT NULL,
    max_drift_ticker  TEXT NOT NULL REFERENCES dim_security (ticker)
);

-- ---------------------------------------------------------------------------
-- fact_daily_holding_returns: one row per holding per RETURN day
-- (the base day has no return, so it is not in this table).
-- ---------------------------------------------------------------------------
CREATE TABLE fact_daily_holding_returns (
    price_date      DATE NOT NULL REFERENCES dim_date (date_key),
    ticker          TEXT NOT NULL REFERENCES dim_security (ticker),
    r               DOUBLE PRECISION NOT NULL,  -- daily return from adjusted close
    w_prev          DOUBLE PRECISION NOT NULL,  -- weight at the previous close, after trades
    contrib         DOUBLE PRECISION NOT NULL,  -- w_prev x r
    linked_contrib  DOUBLE PRECISION NOT NULL,  -- contrib x growth_prev
    PRIMARY KEY (price_date, ticker)
);

-- ---------------------------------------------------------------------------
-- fact_correlation: 13 x 13 = 169 rows in long format (both orders, diagonal
-- included). sort_a / sort_b give the display order for the Power BI matrix.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_correlation (
    ticker_a     TEXT NOT NULL REFERENCES dim_security (ticker),
    ticker_b     TEXT NOT NULL REFERENCES dim_security (ticker),
    correlation  DOUBLE PRECISION NOT NULL CHECK (correlation BETWEEN -1.000000001 AND 1.000000001),
    sort_a       SMALLINT NOT NULL,
    sort_b       SMALLINT NOT NULL,
    PRIMARY KEY (ticker_a, ticker_b)
);

-- ---------------------------------------------------------------------------
-- fact_drawdown_episodes: one row per drawdown, for the portfolio and SPY.
-- recovery_date and days_to_recover are NULL while not yet recovered.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_drawdown_episodes (
    series             TEXT     NOT NULL CHECK (series IN ('PORTFOLIO', 'SPY')),
    episode_no         SMALLINT NOT NULL,     -- 1 = earliest
    peak_date          DATE     NOT NULL REFERENCES dim_date (date_key),
    trough_date        DATE     NOT NULL REFERENCES dim_date (date_key),
    recovery_date      DATE     REFERENCES dim_date (date_key),
    depth              DOUBLE PRECISION NOT NULL CHECK (depth < 0),
    days_to_trough     INTEGER  NOT NULL,     -- trading days, peak to trough
    days_to_recover    INTEGER,               -- trading days, trough to recovery
    days_peak_to_recovery INTEGER,            -- trading days, peak to recovery
    recovered          BOOLEAN  NOT NULL,
    depth_rank         SMALLINT NOT NULL,     -- 1 = deepest within its series
    PRIMARY KEY (series, episode_no)
);

-- ---------------------------------------------------------------------------
-- fact_risk_contribution: share of portfolio variance by holding.
-- method HISTORICAL = actual daily weights over all return days.
-- method CURRENT    = latest weights x covariance of the last 252 return days.
-- Sector totals come from dim_security in Power BI.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_risk_contribution (
    method             TEXT NOT NULL CHECK (method IN ('HISTORICAL', 'CURRENT')),
    ticker             TEXT NOT NULL REFERENCES dim_security (ticker),
    weight_used        DOUBLE PRECISION NOT NULL,  -- HISTORICAL: average w_prev; CURRENT: latest weight
    risk_contribution  DOUBLE PRECISION NOT NULL,  -- fraction of variance; sums to 1 per method
    window_start       DATE NOT NULL REFERENCES dim_date (date_key),
    window_end         DATE NOT NULL REFERENCES dim_date (date_key),
    return_days        INTEGER NOT NULL,
    PRIMARY KEY (method, ticker)
);

-- ---------------------------------------------------------------------------
-- fact_holding_beta: full-period beta of each holding vs SPY.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_holding_beta (
    ticker       TEXT PRIMARY KEY REFERENCES dim_security (ticker),
    beta_excess  DOUBLE PRECISION NOT NULL,  -- the reported beta (excess returns)
    beta_raw     DOUBLE PRECISION NOT NULL   -- for comparison only
);

-- ---------------------------------------------------------------------------
-- analysis_summary: full-period reference numbers. The Stage 7 DAX measures
-- must reproduce these. spy_value is NULL where a metric has no SPY meaning.
-- ---------------------------------------------------------------------------
CREATE TABLE analysis_summary (
    metric_key       TEXT PRIMARY KEY,
    metric_name      TEXT NOT NULL,
    portfolio_value  DOUBLE PRECISION,
    spy_value        DOUBLE PRECISION,
    unit             TEXT NOT NULL,      -- fraction, ratio, days, USD
    definition       TEXT NOT NULL,
    period_start     DATE NOT NULL REFERENCES dim_date (date_key),
    period_end       DATE NOT NULL REFERENCES dim_date (date_key),
    sort_order       SMALLINT NOT NULL
);
