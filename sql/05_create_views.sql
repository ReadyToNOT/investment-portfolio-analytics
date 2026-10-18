-- sql/05_create_views.sql
-- vw_daily_holdings: shares held and market value per holding per trading day.
--
-- A VIEW is a saved query that behaves like a table. It stores no data of its
-- own: every time you SELECT from it, PostgreSQL re-runs the query, so it is
-- always in sync with fact_prices and fact_transactions.
--
-- Grain: one row per holding per trading day, from that holding's first trade
-- to the last price date. SPY never appears (it has no trades).
--
-- Conventions (from data/processed/README.md):
-- * Trades happen at the close, so on a trade date shares_held already
--   includes that day's trade, and market_value is measured after it.
-- * market_value = shares_held x close_price (the actual, unadjusted close).
--   Cash dividends are NOT added to market value, because the sample portfolio
--   holds no cash. Dividends ARE counted in returns, through adj_close_price
--   (Stage 5). The dashboard Notes page will state this.
--
-- Run by src/build_model.py right after 04_load_model.sql.

CREATE VIEW vw_daily_holdings AS
WITH
-- Several trades in the same ticker on the same day are combined into one row.
daily_trades AS (
    SELECT ticker,
           trade_date,
           SUM(signed_shares)    AS shares_traded,
           SUM(net_contribution) AS net_contribution
    FROM fact_transactions
    GROUP BY ticker, trade_date
),
positions AS (
    SELECT p.price_date,
           p.ticker,
           p.close_price,
           COALESCE(d.shares_traded, 0)    AS shares_traded,
           COALESCE(d.net_contribution, 0) AS net_contribution,
           -- A WINDOW FUNCTION computes across related rows without collapsing
           -- them. SUM(...) OVER (PARTITION BY ticker ORDER BY price_date ...)
           -- is a running total per ticker: on each day it adds up every trade
           -- from the first day up to and including that day.
           SUM(COALESCE(d.shares_traded, 0)) OVER (
               PARTITION BY p.ticker
               ORDER BY p.price_date
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) AS shares_held,
           -- Same idea without ORDER BY: one value for the whole ticker.
           MIN(d.trade_date) OVER (PARTITION BY p.ticker) AS first_trade_date
    FROM fact_prices p
    LEFT JOIN daily_trades d
           ON d.ticker = p.ticker AND d.trade_date = p.price_date
),
valued AS (
    SELECT price_date,
           ticker,
           shares_traded,
           shares_held,
           close_price,
           shares_held * close_price AS market_value,
           net_contribution
    FROM positions
    WHERE price_date >= first_trade_date   -- NULL for SPY, so SPY drops out
)
SELECT price_date,
       ticker,
       shares_traded,
       shares_held,
       close_price,
       market_value,
       net_contribution,
       -- Weight = this holding's value / total portfolio value that day (a fraction).
       -- NULLIF(x, 0) turns a zero total into NULL so we never divide by zero.
       market_value / NULLIF(SUM(market_value) OVER (PARTITION BY price_date), 0) AS actual_weight
FROM valued;
