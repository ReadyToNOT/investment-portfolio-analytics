-- sql/03_create_model.sql
-- The reporting model (a "star schema"): small DIMENSION tables that describe
-- things (securities, dates) and FACT tables that hold the measurements
-- (prices, trades, rates). Power BI will relate each dimension to its facts
-- one-to-many: one row in dim_security matches many rows in fact_prices.
--
-- Every model table is rebuilt from the stg_* tables on each run, so this file
-- DROPs and re-CREATEs them. Nothing is lost: the staging tables and the CSVs
-- are the source of truth. Rebuilding also means a column change here takes
-- effect on the next run without any manual ALTER TABLE.
--
-- Run by src/build_model.py (inside one transaction with 04 and 05).

-- Drop the view first because it depends on the tables.
-- CASCADE also drops anything else that depends on a table (for example a
-- foreign key pointing at it), so the drop order can't fail.
DROP VIEW  IF EXISTS vw_daily_holdings;
DROP TABLE IF EXISTS fact_prices, fact_transactions, fact_rates CASCADE;
DROP TABLE IF EXISTS dim_security, dim_date CASCADE;

-- ---------------------------------------------------------------------------
-- dim_security: one row per ticker (12 holdings + SPY).
-- The ticker itself is the key ("natural key"). It is short, stable and
-- already unique, so a separate number ID would add a join without benefit.
-- ---------------------------------------------------------------------------
CREATE TABLE dim_security (
    ticker         TEXT PRIMARY KEY,
    security_name  TEXT NOT NULL,
    asset_class    TEXT NOT NULL,                 -- Stock or ETF
    sector         TEXT NOT NULL,
    role           TEXT NOT NULL CHECK (role IN ('HOLDING', 'BENCHMARK')),
    -- Target weight as a FRACTION (0.12 = 12 percent). All weights in the model
    -- use fractions so Power BI can format them as percentages consistently.
    -- NULL for the benchmark, which is not part of the portfolio.
    target_weight  NUMERIC(6, 4),
    currency       TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- dim_date: one row per CALENDAR day, with no gaps, from the first to the last
-- price date. Power BI's "Mark as date table" requires exactly that: unique,
-- contiguous dates. Weekends and holidays are included and flagged, so
-- visuals can filter to trading days.
-- ---------------------------------------------------------------------------
CREATE TABLE dim_date (
    date_key                  DATE PRIMARY KEY,
    year                      SMALLINT NOT NULL,
    quarter                   SMALLINT NOT NULL,
    quarter_label             TEXT     NOT NULL,  -- e.g. 2024 Q1
    month_num                 SMALLINT NOT NULL,  -- 1 to 12
    month_name                TEXT     NOT NULL,  -- Jan, Feb, ...
    year_month                TEXT     NOT NULL,  -- e.g. 2024-01 (sorts correctly as text)
    month_start               DATE     NOT NULL,
    iso_week                  SMALLINT NOT NULL,
    day_of_week               SMALLINT NOT NULL,  -- 1 = Monday ... 7 = Sunday
    day_name                  TEXT     NOT NULL,
    is_weekday                BOOLEAN  NOT NULL,
    is_trading_day            BOOLEAN  NOT NULL,  -- the benchmark (SPY) has a price that day
    is_month_end_trading_day  BOOLEAN  NOT NULL,  -- last trading day of its month (for monthly rebalancing later)
    is_portfolio_period       BOOLEAN  NOT NULL   -- on or after the first trade (before = warm-up history only)
);

-- ---------------------------------------------------------------------------
-- fact_prices: one row per ticker per trading day.
-- close_price      = actual (unadjusted) close: use for market value.
-- adj_close_price  = dividend-adjusted close: use for returns.
-- dividend_per_share = cash dividend with its ex-date on that day, else 0.
--   Dividends are folded in here instead of a sixth table: they are one number
--   per ticker per day, exactly this table's grain ("grain" = what one row means).
-- REFERENCES creates a FOREIGN KEY: PostgreSQL refuses a row whose ticker is
-- not in dim_security or whose date is not in dim_date.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_prices (
    price_date          DATE NOT NULL REFERENCES dim_date (date_key),
    ticker              TEXT NOT NULL REFERENCES dim_security (ticker),
    open_price          DOUBLE PRECISION,
    high_price          DOUBLE PRECISION,
    low_price           DOUBLE PRECISION,
    close_price         DOUBLE PRECISION NOT NULL,
    adj_close_price     DOUBLE PRECISION NOT NULL,
    volume              BIGINT,
    dividend_per_share  DOUBLE PRECISION NOT NULL DEFAULT 0,
    PRIMARY KEY (ticker, price_date)
);
-- An INDEX is a lookup structure (like a book index) that speeds up searches
-- and joins on a column. The primary key already indexes (ticker, price_date);
-- this one helps queries that look up all tickers on one date.
CREATE INDEX ix_fact_prices_date ON fact_prices (price_date);

-- ---------------------------------------------------------------------------
-- fact_transactions: one row per trade, priced at that day's close.
-- shares is always positive; signed_shares is + for BUY and - for SELL, so a
-- running total of signed_shares gives the shares held.
-- net_contribution is the money added (+) or withdrawn (-) that day. The
-- time-weighted return in Stage 5 must strip these cash flows out.
-- trade_price is left nullable on purpose: a missing price is reported by a
-- validation check with a clear message instead of aborting the load.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_transactions (
    transaction_id    TEXT PRIMARY KEY,
    trade_date        DATE NOT NULL REFERENCES dim_date (date_key),
    ticker            TEXT NOT NULL REFERENCES dim_security (ticker),
    transaction_type  TEXT NOT NULL CHECK (transaction_type IN ('BUY', 'SELL')),
    shares            NUMERIC(18, 4) NOT NULL CHECK (shares > 0),
    signed_shares     NUMERIC(18, 4) NOT NULL,
    trade_price       DOUBLE PRECISION,
    trade_value       DOUBLE PRECISION,      -- shares x trade_price (always positive)
    net_contribution  DOUBLE PRECISION       -- signed_shares x trade_price
);

-- ---------------------------------------------------------------------------
-- fact_rates: the FRED DTB3 series exactly as published, one row per FRED date.
-- dtb3_discount_pct is in percent on a DISCOUNT basis and is NULL on days FRED
-- has no value. Converting to a daily risk-free rate and forward-filling the
-- gaps happens in Stage 5 (decided in Stage 3), so this table stays a faithful
-- copy that can be checked against the raw file.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_rates (
    rate_date          DATE PRIMARY KEY REFERENCES dim_date (date_key),
    dtb3_discount_pct  DOUBLE PRECISION
);
