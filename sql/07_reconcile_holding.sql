-- sql/07_reconcile_holding.sql
-- Hand reconciliation helper for ONE holding (AAPL), for docs/reconciliation.md.
-- Run in pgAdmin: open the file, press F5.
--
-- Why AAPL: it is the only holding with a SELL (T019, 20 shares on 2025-08-01),
-- so it tests both directions of the running share total.
-- Dates: the first buy, the day before the sell, the sell day, and the last day.
--
-- The shares_from_trade_log column is computed a DIFFERENT way from the view:
-- a sub-query that adds up the trade log directly for each date, instead of the
-- view's running-total window function. Two methods agreeing is the point.

WITH check_dates AS (
    -- VALUES builds a small table from typed-in rows.
    SELECT d::date AS check_date
    FROM (VALUES ('2023-11-01'), ('2025-07-31'), ('2025-08-01')) AS v(d)
    UNION ALL
    SELECT MAX(price_date) FROM fact_prices
)
SELECT c.check_date,
       'AAPL' AS ticker,
       -- Shares held = every AAPL trade on or before this date, + for BUY, - for SELL.
       (SELECT SUM(CASE WHEN t.transaction_type = 'BUY' THEN t.shares ELSE -t.shares END)
          FROM stg_transactions t
         WHERE t.ticker = 'AAPL' AND t.trade_date <= c.check_date)        AS shares_from_trade_log,
       p.close_price                                                       AS close_from_prices,
       ROUND(((SELECT SUM(CASE WHEN t.transaction_type = 'BUY' THEN t.shares ELSE -t.shares END)
                 FROM stg_transactions t
                WHERE t.ticker = 'AAPL' AND t.trade_date <= c.check_date)
              * p.close_price)::numeric, 2)                                AS value_recomputed,
       v.shares_held                                                       AS shares_in_view,
       ROUND(v.market_value::numeric, 2)                                   AS value_in_view,
       ROUND((v.actual_weight * 100)::numeric, 2)                          AS weight_pct_in_view
FROM check_dates c
JOIN stg_prices p        ON p.ticker = 'AAPL' AND p.price_date = c.check_date
JOIN vw_daily_holdings v ON v.ticker = 'AAPL' AND v.price_date = c.check_date
ORDER BY c.check_date;
