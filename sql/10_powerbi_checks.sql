-- Compounded portfolio return over calendar 2024, independent of Power BI.
SELECT EXP(SUM(LN(1 + r_p))) - 1 AS total_return_2024,
       COUNT(r_p)                AS return_days_2024
FROM fact_daily_portfolio
WHERE price_date BETWEEN DATE '2024-01-01' AND DATE '2024-12-31';


-- MSFT weight on the last price date vs its target weight.
SELECT v.ticker,
       v.price_date,
       v.actual_weight,
       s.target_weight,
       v.actual_weight - s.target_weight AS drift
FROM vw_daily_holdings v
JOIN dim_security s ON s.ticker = v.ticker
WHERE v.ticker = 'MSFT'
  AND v.price_date = DATE '2026-10-16';