-- sql/06_validate_model.sql
-- Validation checks on the model. ONE query that returns one row per check:
--   check_id | check_name | expected | actual | passed
-- src/build_model.py runs it after every build and fails if any row says false.
-- You can also run it in pgAdmin (open the file, press F5) and read the table.
--
-- Pattern used: each check is a small SELECT producing the same five columns,
-- and UNION ALL stacks them. "expected" and "actual" are cast to TEXT (::text)
-- so numbers, dates and true/false can share one column.
-- Most checks count "bad rows", where the expected answer is 0.

WITH
trading_days AS (
    SELECT date_key FROM dim_date WHERE is_trading_day
),
holdings AS (
    SELECT ticker FROM dim_security WHERE role = 'HOLDING'
),
net_shares AS (                 -- final position per ticker according to the trade log
    SELECT ticker, SUM(signed_shares) AS shares
    FROM fact_transactions
    GROUP BY ticker
),
last_view_day AS (              -- final position per ticker according to the view
    SELECT v.ticker, v.shares_held
    FROM vw_daily_holdings v
    WHERE v.price_date = (SELECT MAX(price_date) FROM vw_daily_holdings)
),
first_trades AS (
    SELECT ticker, MIN(trade_date) AS first_trade
    FROM fact_transactions
    GROUP BY ticker
),
daily_weight_totals AS (
    SELECT price_date, SUM(actual_weight) AS total_weight
    FROM vw_daily_holdings
    GROUP BY price_date
),
-- For each portfolio trading day, the most recent DTB3 value on or before it.
-- A LATERAL join lets the sub-query refer to the current outer row (d.date_key).
latest_rate AS (
    SELECT d.date_key, r.rate_date
    FROM dim_date d
    LEFT JOIN LATERAL (
        SELECT rate_date
        FROM fact_rates
        WHERE dtb3_discount_pct IS NOT NULL
          AND rate_date <= d.date_key
        ORDER BY rate_date DESC
        LIMIT 1
    ) r ON TRUE
    WHERE d.is_trading_day AND d.is_portfolio_period
)

-- ---------------- dim_security ----------------
SELECT 'M01' AS check_id, 'dim_security has one row per lookup row' AS check_name,
       (SELECT COUNT(*) FROM stg_security_lookup)::text AS expected,
       (SELECT COUNT(*) FROM dim_security)::text        AS actual,
       (SELECT COUNT(*) FROM stg_security_lookup) = (SELECT COUNT(*) FROM dim_security) AS passed

UNION ALL
SELECT 'M02', 'Exactly one BENCHMARK security',
       '1', COUNT(*)::text, COUNT(*) = 1
FROM dim_security WHERE role = 'BENCHMARK'

UNION ALL
SELECT 'M03', 'Holding target weights add up to 1 (100 percent)',
       '1.0000', SUM(target_weight)::text, SUM(target_weight) = 1
FROM dim_security WHERE role = 'HOLDING'

UNION ALL
SELECT 'M04', 'Every holding has a target weight; benchmark has none',
       '0 bad rows', COUNT(*)::text, COUNT(*) = 0
FROM dim_security
WHERE (role = 'HOLDING' AND target_weight IS NULL)
   OR (role = 'BENCHMARK' AND target_weight IS NOT NULL)

-- ---------------- dim_date ----------------
-- Subtracting two DATEs in PostgreSQL gives a whole number of days.
UNION ALL
SELECT 'M05', 'dim_date has no missing calendar days',
       (MAX(date_key) - MIN(date_key) + 1)::text, COUNT(*)::text,
       COUNT(*) = MAX(date_key) - MIN(date_key) + 1
FROM dim_date

UNION ALL
SELECT 'M06', 'dim_date spans first to last price date',
       (SELECT MIN(price_date) || ' to ' || MAX(price_date) FROM fact_prices),
       MIN(date_key) || ' to ' || MAX(date_key),
       MIN(date_key) = (SELECT MIN(price_date) FROM fact_prices)
   AND MAX(date_key) = (SELECT MAX(price_date) FROM fact_prices)
FROM dim_date

UNION ALL
SELECT 'M07', 'Trading days in dim_date = benchmark price rows',
       (SELECT COUNT(*) FROM fact_prices p JOIN dim_security s USING (ticker) WHERE s.role = 'BENCHMARK')::text,
       (SELECT COUNT(*) FROM trading_days)::text,
       (SELECT COUNT(*) FROM fact_prices p JOIN dim_security s USING (ticker) WHERE s.role = 'BENCHMARK')
         = (SELECT COUNT(*) FROM trading_days)

UNION ALL
SELECT 'M08', 'No trading day falls on a weekend',
       '0 bad rows', COUNT(*)::text, COUNT(*) = 0
FROM dim_date WHERE is_trading_day AND NOT is_weekday

UNION ALL
SELECT 'M09', 'Exactly one month-end trading day per month',
       '0 bad months', COUNT(*)::text, COUNT(*) = 0
FROM (
    SELECT year_month
    FROM dim_date
    GROUP BY year_month
    HAVING COUNT(*) FILTER (WHERE is_month_end_trading_day) <> 1   -- HAVING filters groups; FILTER counts only matching rows
) bad

-- ---------------- fact_prices ----------------
UNION ALL
SELECT 'M10', 'fact_prices row count = stg_prices',
       (SELECT COUNT(*) FROM stg_prices)::text, (SELECT COUNT(*) FROM fact_prices)::text,
       (SELECT COUNT(*) FROM stg_prices) = (SELECT COUNT(*) FROM fact_prices)

UNION ALL
SELECT 'M11', 'Every ticker has a price on every trading day',
       '0 missing', COUNT(*)::text, COUNT(*) = 0
FROM dim_security s
CROSS JOIN trading_days d                -- every (ticker, trading day) pair that SHOULD exist
LEFT JOIN fact_prices p ON p.ticker = s.ticker AND p.price_date = d.date_key
WHERE p.ticker IS NULL                   -- ...that doesn't

UNION ALL
SELECT 'M12', 'No prices on non-trading days',
       '0 bad rows', COUNT(*)::text, COUNT(*) = 0
FROM fact_prices p JOIN dim_date d ON d.date_key = p.price_date
WHERE NOT d.is_trading_day

UNION ALL
SELECT 'M13', 'No zero or negative close / adjusted close',
       '0 bad rows', COUNT(*)::text, COUNT(*) = 0
FROM fact_prices WHERE close_price <= 0 OR adj_close_price <= 0

UNION ALL
SELECT 'M14', 'Every dividend landed on a price row',
       (SELECT COUNT(*) FROM stg_dividends)::text,
       COUNT(*)::text,
       COUNT(*) = (SELECT COUNT(*) FROM stg_dividends)
FROM fact_prices WHERE dividend_per_share > 0

UNION ALL
SELECT 'M15', 'Dividend total matches staging (to 1e-9)',
       ROUND((SELECT SUM(dividend_per_share) FROM stg_dividends)::numeric, 6)::text,
       ROUND(SUM(dividend_per_share)::numeric, 6)::text,
       ABS(SUM(dividend_per_share) - (SELECT SUM(dividend_per_share) FROM stg_dividends)) < 1e-9
FROM fact_prices

-- ---------------- fact_transactions ----------------
UNION ALL
SELECT 'M16', 'fact_transactions row count = stg_transactions',
       (SELECT COUNT(*) FROM stg_transactions)::text, (SELECT COUNT(*) FROM fact_transactions)::text,
       (SELECT COUNT(*) FROM stg_transactions) = (SELECT COUNT(*) FROM fact_transactions)

UNION ALL
SELECT 'M17', 'Every trade has a price on its trade date',
       '0 unpriced', COUNT(*)::text, COUNT(*) = 0
FROM fact_transactions WHERE trade_price IS NULL

UNION ALL
SELECT 'M18', 'Benchmark is never traded',
       '0 trades', COUNT(*)::text, COUNT(*) = 0
FROM fact_transactions t JOIN dim_security s USING (ticker)
WHERE s.role = 'BENCHMARK'

UNION ALL
SELECT 'M19', 'Every holding has at least one trade',
       '0 untraded', COUNT(*)::text, COUNT(*) = 0
FROM holdings h LEFT JOIN first_trades f USING (ticker)
WHERE f.ticker IS NULL

-- ---------------- vw_daily_holdings ----------------
UNION ALL
SELECT 'M20', 'View row count = trading days held, summed over holdings',
       (SELECT COUNT(*) FROM first_trades f JOIN trading_days d ON d.date_key >= f.first_trade)::text,
       (SELECT COUNT(*) FROM vw_daily_holdings)::text,
       (SELECT COUNT(*) FROM first_trades f JOIN trading_days d ON d.date_key >= f.first_trade)
         = (SELECT COUNT(*) FROM vw_daily_holdings)

UNION ALL
SELECT 'M21', 'No negative share balance on any day',
       '0 bad rows', COUNT(*)::text, COUNT(*) = 0
FROM vw_daily_holdings WHERE shares_held < 0

UNION ALL
SELECT 'M22', 'Final shares in view = net shares in trade log',
       '0 mismatches', COUNT(*)::text, COUNT(*) = 0
FROM net_shares n
FULL JOIN last_view_day v USING (ticker)   -- FULL JOIN keeps unmatched rows from BOTH sides
WHERE n.shares IS DISTINCT FROM v.shares_held   -- like <>, but treats NULL vs value as different

UNION ALL
SELECT 'M23', 'Weights add up to 1 on every day (to 1e-9)',
       '0 bad days', COUNT(*)::text, COUNT(*) = 0
FROM daily_weight_totals WHERE ABS(total_weight - 1) > 1e-9

UNION ALL
SELECT 'M24', 'Net contributions in view = trade log total (to 0.01)',
       ROUND((SELECT SUM(net_contribution) FROM fact_transactions)::numeric, 2)::text,
       ROUND(SUM(net_contribution)::numeric, 2)::text,
       ABS(SUM(net_contribution) - (SELECT SUM(net_contribution) FROM fact_transactions)) < 0.01
FROM vw_daily_holdings

UNION ALL
-- Cross-check with Stage 3: check_raw_data.py computed the opening value
-- independently (in pandas) as 99,455.49. Same inputs, so it must match.
SELECT 'M25', 'Opening portfolio value matches Stage 3 (99455.49)',
       '99455.49', ROUND(SUM(market_value)::numeric, 2)::text,
       ROUND(SUM(market_value)::numeric, 2) = 99455.49
FROM vw_daily_holdings
WHERE price_date = (SELECT MIN(trade_date) FROM fact_transactions)

-- ---------------- fact_rates ----------------
UNION ALL
SELECT 'M26', 'fact_rates row count = stg_rates',
       (SELECT COUNT(*) FROM stg_rates)::text, (SELECT COUNT(*) FROM fact_rates)::text,
       (SELECT COUNT(*) FROM stg_rates) = (SELECT COUNT(*) FROM fact_rates)

UNION ALL
SELECT 'M27', 'Missing DTB3 values kept as NULL (same count as staging)',
       (SELECT COUNT(*) - COUNT(dtb3_pct) FROM stg_rates)::text,
       (COUNT(*) - COUNT(dtb3_discount_pct))::text,
       COUNT(*) - COUNT(dtb3_discount_pct) = (SELECT COUNT(*) - COUNT(dtb3_pct) FROM stg_rates)
FROM fact_rates

UNION ALL
-- Stage 5 forward-fills missing rates. This makes sure no fill reaches back
-- more than 7 calendar days (a long gap would mean a data problem, not a holiday).
SELECT 'M28', 'Every portfolio trading day has a DTB3 value within 7 days',
       '0 bad days', COUNT(*)::text, COUNT(*) = 0
FROM latest_rate
WHERE rate_date IS NULL OR date_key - rate_date > 7

ORDER BY check_id;
