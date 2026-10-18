-- sql/04_load_model.sql
-- Fills the model tables from the stg_* tables with INSERT ... SELECT
-- (insert the result of a query instead of typed-in values).
-- Order matters: dimensions first, because the facts' foreign keys point at them.
-- Run by src/build_model.py right after 03_create_model.sql.

-- ---------------------------------------------------------------------------
-- 1) dim_security: copy the lookup, turning 12 (percent) into 0.12 (fraction).
-- ---------------------------------------------------------------------------
INSERT INTO dim_security (ticker, security_name, asset_class, sector, role, target_weight, currency)
SELECT ticker,
       security_name,
       asset_class,
       sector,
       role,
       target_weight_pct / 100.0,
       currency
FROM stg_security_lookup;

-- ---------------------------------------------------------------------------
-- 2) dim_date: one row per calendar day between the first and last price date.
-- A CTE ("WITH name AS (...)") is a named sub-query you can use like a
-- temporary table further down the same statement.
-- generate_series(start, stop, step) produces one row per day.
-- EXTRACT(part FROM date) pulls out a piece of a date (year, month, ...).
-- to_char(date, pattern) formats a date as text, e.g. 'Mon' gives Jan.
-- ---------------------------------------------------------------------------
INSERT INTO dim_date (
    date_key, year, quarter, quarter_label, month_num, month_name, year_month,
    month_start, iso_week, day_of_week, day_name, is_weekday, is_trading_day,
    is_month_end_trading_day, is_portfolio_period
)
WITH bounds AS (
    SELECT MIN(price_date) AS first_day, MAX(price_date) AS last_day
    FROM stg_prices
),
-- Trading days = the days the benchmark has a price (its calendar is the market's).
trading_days AS (
    SELECT p.price_date
    FROM stg_prices p
    JOIN stg_security_lookup s ON s.ticker = p.ticker AND s.role = 'BENCHMARK'
),
-- The last trading day of each month: group trading days by month, take the MAX.
-- date_trunc('month', d) rounds a date down to the 1st of its month.
month_ends AS (
    SELECT MAX(price_date) AS price_date
    FROM trading_days
    GROUP BY date_trunc('month', price_date)
),
portfolio_start AS (
    SELECT MIN(trade_date) AS first_trade FROM stg_transactions
),
calendar AS (
    SELECT gs::date AS d
    FROM bounds, generate_series(bounds.first_day, bounds.last_day, INTERVAL '1 day') AS gs
)
SELECT c.d,
       EXTRACT(YEAR FROM c.d)::smallint,
       EXTRACT(QUARTER FROM c.d)::smallint,
       EXTRACT(YEAR FROM c.d)::int || ' Q' || EXTRACT(QUARTER FROM c.d)::int,
       EXTRACT(MONTH FROM c.d)::smallint,
       to_char(c.d, 'Mon'),
       to_char(c.d, 'YYYY-MM'),
       date_trunc('month', c.d)::date,
       EXTRACT(WEEK FROM c.d)::smallint,          -- ISO week number
       EXTRACT(ISODOW FROM c.d)::smallint,        -- 1 = Monday ... 7 = Sunday
       trim(to_char(c.d, 'Day')),                 -- trim removes padding spaces
       EXTRACT(ISODOW FROM c.d) <= 5,
       td.price_date IS NOT NULL,                 -- found in the benchmark's calendar?
       me.price_date IS NOT NULL,
       c.d >= ps.first_trade
FROM calendar c
CROSS JOIN portfolio_start ps                     -- CROSS JOIN with a one-row table = attach that value to every row
LEFT JOIN trading_days td ON td.price_date = c.d
LEFT JOIN month_ends   me ON me.price_date = c.d;

-- ---------------------------------------------------------------------------
-- 3) fact_prices: prices plus that day's dividend (0 when there is none).
-- LEFT JOIN keeps every price row even when no dividend matches;
-- COALESCE(x, 0) returns x, or 0 when x is NULL.
-- ---------------------------------------------------------------------------
INSERT INTO fact_prices (
    price_date, ticker, open_price, high_price, low_price, close_price,
    adj_close_price, volume, dividend_per_share
)
SELECT p.price_date,
       p.ticker,
       p.open_price,
       p.high_price,
       p.low_price,
       p.close_price,
       p.adj_close_price,
       p.volume,
       COALESCE(d.dividend_per_share, 0)
FROM stg_prices p
LEFT JOIN stg_dividends d
       ON d.ticker = p.ticker AND d.ex_date = p.price_date;

-- ---------------------------------------------------------------------------
-- 4) fact_transactions: each trade priced at the close on its trade date.
-- CASE WHEN ... THEN ... ELSE ... END is SQL's if/else.
-- ---------------------------------------------------------------------------
INSERT INTO fact_transactions (
    transaction_id, trade_date, ticker, transaction_type, shares,
    signed_shares, trade_price, trade_value, net_contribution
)
SELECT t.transaction_id,
       t.trade_date,
       t.ticker,
       t.transaction_type,
       t.shares,
       CASE WHEN t.transaction_type = 'SELL' THEN -t.shares ELSE t.shares END,
       p.close_price,
       t.shares * p.close_price,
       CASE WHEN t.transaction_type = 'SELL' THEN -t.shares ELSE t.shares END * p.close_price
FROM stg_transactions t
LEFT JOIN stg_prices p
       ON p.ticker = t.ticker AND p.price_date = t.trade_date;

-- ---------------------------------------------------------------------------
-- 5) fact_rates: straight copy, NULLs (missing days) kept as NULL.
-- ---------------------------------------------------------------------------
INSERT INTO fact_rates (rate_date, dtb3_discount_pct)
SELECT rate_date, dtb3_pct
FROM stg_rates;
