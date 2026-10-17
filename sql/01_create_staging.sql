-- sql/01_create_staging.sql
-- Staging tables: plain copies of the raw and input CSVs, with types and
-- primary keys. A primary key is a column (or pair of columns) that must be
-- unique, so PostgreSQL itself refuses duplicate rows.
-- Stage 4 reshapes these into dim_* and fact_* tables.
-- "IF NOT EXISTS" makes this safe to run every time.

CREATE TABLE IF NOT EXISTS stg_prices (
    price_date       DATE              NOT NULL,
    ticker           TEXT              NOT NULL,
    open_price       DOUBLE PRECISION,
    high_price       DOUBLE PRECISION,
    low_price        DOUBLE PRECISION,
    close_price      DOUBLE PRECISION,  -- unadjusted close: use for market value
    adj_close_price  DOUBLE PRECISION,  -- dividend-adjusted close: use for returns
    volume           BIGINT,
    PRIMARY KEY (ticker, price_date)
);

CREATE TABLE IF NOT EXISTS stg_dividends (
    ex_date             DATE             NOT NULL,
    ticker              TEXT             NOT NULL,
    dividend_per_share  DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (ticker, ex_date)
);

CREATE TABLE IF NOT EXISTS stg_splits (
    split_date   DATE             NOT NULL,
    ticker       TEXT             NOT NULL,
    split_ratio  DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (ticker, split_date)
);

CREATE TABLE IF NOT EXISTS stg_rates (
    rate_date  DATE PRIMARY KEY,
    dtb3_pct   DOUBLE PRECISION      -- NULL on days FRED has no value
);

CREATE TABLE IF NOT EXISTS stg_security_lookup (
    ticker             TEXT PRIMARY KEY,
    security_name      TEXT,
    asset_class        TEXT,
    sector             TEXT,
    role               TEXT,
    target_weight_pct  NUMERIC(6, 2),   -- NULL for SPY (benchmark)
    currency           TEXT
);

CREATE TABLE IF NOT EXISTS stg_transactions (
    transaction_id    TEXT PRIMARY KEY,
    trade_date        DATE          NOT NULL,
    ticker            TEXT          NOT NULL,
    transaction_type  TEXT          NOT NULL,
    shares            NUMERIC(18, 4) NOT NULL
);

CREATE TABLE IF NOT EXISTS stg_download_log (
    source             TEXT NOT NULL,
    series             TEXT NOT NULL,
    row_count          INTEGER,
    first_date         DATE,
    last_date          DATE,
    requested_start    TEXT,
    requested_end      TEXT,
    downloaded_at_utc  TIMESTAMP,
    library            TEXT,
    library_version    TEXT,
    PRIMARY KEY (source, series)
);
