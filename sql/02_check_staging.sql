-- sql/02_check_staging.sql
-- Run these one at a time in pgAdmin (Query Tool: highlight one query, press F5).
-- Compare the results with the output of ingest_prices.py, ingest_rates.py and
-- check_raw_data.py.

-- 1) Row count in every staging table.
--    UNION ALL stacks the results of several SELECTs into one result table.
--    Should match the "Loaded N rows" lines from load_staging.py.
SELECT 'stg_prices' AS table_name, COUNT(*) AS row_count FROM stg_prices
UNION ALL SELECT 'stg_dividends',       COUNT(*) FROM stg_dividends
UNION ALL SELECT 'stg_splits',          COUNT(*) FROM stg_splits
UNION ALL SELECT 'stg_rates',           COUNT(*) FROM stg_rates
UNION ALL SELECT 'stg_security_lookup', COUNT(*) FROM stg_security_lookup
UNION ALL SELECT 'stg_transactions',    COUNT(*) FROM stg_transactions
UNION ALL SELECT 'stg_download_log',    COUNT(*) FROM stg_download_log;

-- 2) Per-ticker row count and date range.
--    GROUP BY makes one output row per ticker; MIN/MAX/COUNT summarize each group.
--    Expect 13 rows, all with the same row count and the same first/last date
--    (matching the table ingest_prices.py printed).
SELECT ticker,
       COUNT(*)        AS trading_days,
       MIN(price_date) AS first_date,
       MAX(price_date) AS last_date
FROM stg_prices
GROUP BY ticker
ORDER BY ticker;

-- 3) Same check, compared with the download log.
--    A JOIN matches rows from two tables on a shared column (here the ticker).
--    Every row should say TRUE in all three match columns.
SELECT p.ticker,
       COUNT(*)            = MAX(l.row_count)  AS rows_match,
       MIN(p.price_date)   = MAX(l.first_date) AS first_match,
       MAX(p.price_date)   = MAX(l.last_date)  AS last_match
FROM stg_prices p
JOIN stg_download_log l
  ON l.source = 'yfinance' AND l.series = p.ticker
GROUP BY p.ticker
ORDER BY p.ticker;

-- 4) Risk-free rate coverage. COUNT(column) skips NULLs, so the difference
--    between the two counts is the number of missing (holiday) values.
--    Should match check_raw_data.py's DTB3 INFO line.
SELECT MIN(rate_date)                   AS first_date,
       MAX(rate_date)                   AS last_date,
       COUNT(*)                         AS total_rows,
       COUNT(dtb3_pct)                  AS rows_with_value,
       COUNT(*) - COUNT(dtb3_pct)       AS missing_values,
       ROUND(AVG(dtb3_pct)::numeric, 3) AS avg_pct
FROM stg_rates;

-- 5) Every trade has a price on its trade date (LEFT JOIN keeps trades even when
--    no price matches; those would show a NULL close). Expect ZERO rows.
SELECT t.transaction_id, t.trade_date, t.ticker
FROM stg_transactions t
LEFT JOIN stg_prices p
  ON p.ticker = t.ticker AND p.price_date = t.trade_date
WHERE p.close_price IS NULL;

-- 6) When was the data downloaded? (This feeds the dashboard's Notes page later.)
SELECT source, MIN(downloaded_at_utc) AS downloaded_from, MAX(downloaded_at_utc) AS downloaded_to,
       MAX(library_version) AS library_version
FROM stg_download_log
GROUP BY source;
