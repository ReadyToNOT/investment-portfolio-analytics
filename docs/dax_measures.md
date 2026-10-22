# DAX measures (Stage 7)

Every measure lives in the `_Measures` table of `dashboard/portfolio_analytics.pbix`.
DAX only aggregates and filters numbers computed in Python/SQL (Stages 5 and 6);
it never recomputes returns or drawdowns from prices.

Sample portfolio, educational project, not investment advice.

Conventions: returns, weights and rates are fractions (formatted as percent).
252 trading days per year. Base day 2023-11-01 has blank returns.
"Expected" values were confirmed on the Checks page on 2026-10-21 against
`analysis_summary` (difference column) or against the SQL queries listed at the end.

---

## 1. Full-period KPI measures (match `analysis_summary`)

| Measure | DAX (summary) | Plain language | Format | Must match (key) | Confirmed value |
|---|---|---|---|---|---|
| Return Days | `COUNT(fact_daily_portfolio[r_p])` | Number of return days in the selection (base day has no return, so it is skipped) | Whole number | return_days | 741 |
| Total Return | `PRODUCTX(fact_daily_portfolio, 1 + r_p) - 1`, blank if no return days | Growth of $1 over the selected days, compounded | Percent, 2 dp | total_return | 0.7214252967 |
| Total Return SPY | same with `r_spy` | Same for the benchmark | Percent, 2 dp | total_return (spy_value) | 0.8724816759 |
| Annualized Return | `POWER(1 + [Total Return], 252 / N) - 1` | Steady yearly rate that gives the same growth | Percent, 2 dp | annualized_return | 0.2028766145 |
| Annualized Return SPY | same with SPY | | Percent, 2 dp | annualized_return (spy) | 0.2377816330 |
| Annualized Volatility | `STDEV.S(r_p) * SQRT(252)`, blank if N < 30 | How much daily returns bounce around, per year. STDEV.S skips blanks and divides by n - 1 | Percent, 2 dp | annualized_volatility | 0.1110836484 |
| Annualized Volatility SPY | same with `r_spy` | | Percent, 2 dp | annualized_volatility (spy) | 0.1525785812 |
| Avg Risk-Free Rate | `POWER(1 + AVERAGE(rf_daily), 252) - 1` | Average T-bill rate over the selection, as a yearly rate. AVERAGE skips blanks | Percent, 2 dp | avg_rf_annual | 0.0444582936 |
| Sharpe Ratio | `DIVIDE([Annualized Return] - [Avg Risk-Free Rate], [Annualized Volatility])`, blank if N < 30 | Extra return above T-bills per unit of volatility | Decimal, 2 dp | sharpe_ratio | 1.4261173724 |
| Sharpe Ratio SPY | same with SPY measures | | Decimal, 2 dp | sharpe_ratio (spy) | 1.2670411391 |
| Max Drawdown | `MIN(fact_daily_portfolio[dd_p])` | Deepest fall from the highest value reached since 2023-11-01 (label says so on every page) | Percent, 2 dp | max_drawdown | -0.1279736807 |
| Max Drawdown SPY | `MIN(dd_spy)` | | Percent, 2 dp | max_drawdown (spy) | -0.1875523416 |
| Excess Return Total | `[Total Return] - [Total Return SPY]` | Percentage points ahead of (+) or behind (-) SPY | Percent, 2 dp | excess_return_total | -0.1510563791 |
| Excess Return Annualized | `[Annualized Return] - [Annualized Return SPY]` | Same, per year | Percent, 2 dp | excess_return_annualized | -0.0349050185 |
| Latest Market Value | `CALCULATE(SUM(market_value), price_date = MAX(price_date))` | Portfolio value on the last selected day (shares x close, no dividends or cash) | Currency, 0 dp | ending_market_value | 204,545.1506 |
| Net Contributions | `SUM(fact_daily_portfolio[net_contribution])` | Buys minus sale proceeds over the selection | Currency, 2 dp | net_contributions | 133,299.4905 |

Not in DAX on purpose: beta (needs a regression). It is read from
`analysis_summary` (full period, labeled) and `beta90_p` (rolling line).

Date-range behavior: every measure above follows the date slicer. Max Drawdown
stays measured from the peak since 2023-11-01 (decision 4 in the Stage 7 plan).
Volatility and Sharpe show blank below 30 return days (assumption, labeled).

## 2. Holding and sector measures

| Measure | DAX (summary) | Plain language | Format |
|---|---|---|---|
| Holding Return | `PRODUCTX(fact_daily_holding_returns, 1 + r) - 1`, only when one ticker is in view | One security's own compounded return (adjusted prices, dividends included). Blank on Total rows | Percent, 2 dp |
| Return Contribution | `DIVIDE(SUM(linked_contrib), growth_prev on the first selected return day)` | Percentage points of portfolio return that came from a holding or sector. Sums exactly to Total Return for any date range (methodology section 9) | Percent, 2 dp |
| Actual Weight | `CALCULATE(SUM(actual_weight), price_date = last selected date)` | Share of portfolio value on the last selected day | Percent, 2 dp |
| Target Weight | `SUM(dim_security[target_weight])` | Planned weight from Stage 2 (blank for SPY) | Percent, 2 dp |
| Weight Drift | `[Actual Weight] - [Target Weight]` | + overweight, - underweight vs plan | Percent, 2 dp |
| Holding Market Value | `CALCULATE(SUM(market_value), price_date = last selected date)` | Dollar value on the last selected day | Currency, 0 dp |

## 3. Chart measures

| Measure | Plain language | Format |
|---|---|---|
| Index Rebased | `100 x index_p / index_p on the first selected date` (first date found with ALLSELECTED(dim_date)). Equals index_p with no date filter | Decimal, 2 dp |
| Index Rebased SPY | Same with `index_spy` | Decimal, 2 dp |

## 4. Check measures (Checks page, hidden in Stage 8)

| Measure | Purpose |
|---|---|
| Check DAX (Portfolio) / (SPY) | SWITCH on `analysis_summary[metric_key]` to the matching measure |
| Check Stored (Portfolio) / (SPY) | `SELECTEDVALUE` of the stored value |
| Check Diff (Portfolio) / (SPY) | DAX minus stored, scientific notation |
| Check Status | PASS if within 1e-9 (fractions, ratios, days) or 1e-6 dollars (USD) |
| Check Total Return 2024 | `CALCULATE([Total Return], dim_date[year] = 2024)` |
| Check Contribution Diff (Full) / (2024) | Sum of contributions minus Total Return |

## 5. Validation results (2026-10-21, from running the model)

- Checks table: 11 of 11 DAX metrics PASS; largest difference 1.40E-14 (avg_rf_annual).
  beta and beta_raw: stored only, by design.
- 2024 sub-period: DAX 0.1635132256; SQL (below) 0.16351322560664516, 252 return days. Match.
- Contribution sums: full period 1.33E-15, 2024 1.83E-15 (both ~0).
- Holdings table totals: Return Contribution 72.14 percent (= Total Return),
  Actual Weight 100.00 percent, Target Weight 100.00 percent, value $204,545.
- Drift hand check, MSFT on 2026-10-16: actual_weight 0.11639117025111803 - target 0.12
  = -0.0036088 (SQL drift -0.0036088297488819643); DAX shows -0.36 percent. Match.

### SQL used

```sql
-- 2024 compounded portfolio return
SELECT EXP(SUM(LN(1 + r_p))) - 1 AS total_return_2024,
       COUNT(r_p)                AS return_days_2024
FROM fact_daily_portfolio
WHERE price_date BETWEEN DATE '2024-01-01' AND DATE '2024-12-31';

-- MSFT drift on the last price date
SELECT v.ticker, v.price_date, v.actual_weight, s.target_weight,
       v.actual_weight - s.target_weight AS drift
FROM vw_daily_holdings v
JOIN dim_security s ON s.ticker = v.ticker
WHERE v.ticker = 'MSFT' AND v.price_date = DATE '2026-10-16';
```

DAX concepts used: filter context, row context, iterators (PRODUCTX),
VAR/RETURN, CALCULATE, REMOVEFILTERS, ALLSELECTED, SWITCH, SELECTEDVALUE,
HASONEVALUE, DIVIDE.

## 6. Full DAX text

```dax
Return Days = COUNT ( fact_daily_portfolio[r_p] )

Total Return =
VAR Growth = PRODUCTX ( fact_daily_portfolio, 1 + fact_daily_portfolio[r_p] )
RETURN IF ( [Return Days] > 0, Growth - 1 )

Total Return SPY =
VAR Growth = PRODUCTX ( fact_daily_portfolio, 1 + fact_daily_portfolio[r_spy] )
RETURN IF ( [Return Days] > 0, Growth - 1 )

Annualized Return =
VAR N = [Return Days]
VAR TR = [Total Return]
RETURN IF ( N > 0, POWER ( 1 + TR, 252 / N ) - 1 )

Annualized Return SPY =
VAR N = [Return Days]
VAR TR = [Total Return SPY]
RETURN IF ( N > 0, POWER ( 1 + TR, 252 / N ) - 1 )

Annualized Volatility =
VAR N = [Return Days]
RETURN IF ( N >= 30, STDEV.S ( fact_daily_portfolio[r_p] ) * SQRT ( 252 ) )

Annualized Volatility SPY =
VAR N = [Return Days]
RETURN IF ( N >= 30, STDEV.S ( fact_daily_portfolio[r_spy] ) * SQRT ( 252 ) )

Avg Risk-Free Rate =
VAR AvgDaily = AVERAGE ( fact_daily_portfolio[rf_daily] )
RETURN IF ( [Return Days] > 0, POWER ( 1 + AvgDaily, 252 ) - 1 )

Sharpe Ratio =
VAR N = [Return Days]
RETURN IF ( N >= 30, DIVIDE ( [Annualized Return] - [Avg Risk-Free Rate], [Annualized Volatility] ) )

Sharpe Ratio SPY =
VAR N = [Return Days]
RETURN IF ( N >= 30, DIVIDE ( [Annualized Return SPY] - [Avg Risk-Free Rate], [Annualized Volatility SPY] ) )

Max Drawdown = MIN ( fact_daily_portfolio[dd_p] )

Max Drawdown SPY = MIN ( fact_daily_portfolio[dd_spy] )

Excess Return Total = [Total Return] - [Total Return SPY]

Excess Return Annualized = [Annualized Return] - [Annualized Return SPY]

Latest Market Value =
VAR LastDay = MAX ( fact_daily_portfolio[price_date] )
RETURN CALCULATE ( SUM ( fact_daily_portfolio[market_value] ), fact_daily_portfolio[price_date] = LastDay )

Net Contributions = SUM ( fact_daily_portfolio[net_contribution] )

Holding Return =
VAR Growth = PRODUCTX ( fact_daily_holding_returns, 1 + fact_daily_holding_returns[r] )
VAR RowsSelected = COUNTROWS ( fact_daily_holding_returns )
RETURN IF ( HASONEVALUE ( dim_security[ticker] ) && RowsSelected > 0, Growth - 1 )

Return Contribution =
VAR FirstDay =
    CALCULATE ( MIN ( fact_daily_holding_returns[price_date] ), REMOVEFILTERS ( dim_security ) )
VAR GrowthBefore =
    CALCULATE ( MAX ( fact_daily_portfolio[growth_prev] ), fact_daily_portfolio[price_date] = FirstDay )
RETURN DIVIDE ( SUM ( fact_daily_holding_returns[linked_contrib] ), GrowthBefore )

Actual Weight =
VAR LastDay = MAX ( vw_daily_holdings[price_date] )
RETURN CALCULATE ( SUM ( vw_daily_holdings[actual_weight] ), vw_daily_holdings[price_date] = LastDay )

Target Weight = SUM ( dim_security[target_weight] )

Weight Drift =
VAR Target = [Target Weight]
RETURN IF ( NOT ISBLANK ( Target ), [Actual Weight] - Target )

Holding Market Value =
VAR LastDay = MAX ( vw_daily_holdings[price_date] )
RETURN CALCULATE ( SUM ( vw_daily_holdings[market_value] ), vw_daily_holdings[price_date] = LastDay )

Index Rebased =
VAR FirstDay = CALCULATE ( MIN ( fact_daily_portfolio[price_date] ), ALLSELECTED ( dim_date ) )
VAR StartIndex =
    CALCULATE ( MAX ( fact_daily_portfolio[index_p] ),
        fact_daily_portfolio[price_date] = FirstDay, ALLSELECTED ( dim_date ) )
VAR TodayIndex = MAX ( fact_daily_portfolio[index_p] )
RETURN IF ( HASONEVALUE ( fact_daily_portfolio[price_date] ), DIVIDE ( TodayIndex, StartIndex ) * 100 )

Index Rebased SPY =
VAR FirstDay = CALCULATE ( MIN ( fact_daily_portfolio[price_date] ), ALLSELECTED ( dim_date ) )
VAR StartIndex =
    CALCULATE ( MAX ( fact_daily_portfolio[index_spy] ),
        fact_daily_portfolio[price_date] = FirstDay, ALLSELECTED ( dim_date ) )
VAR TodayIndex = MAX ( fact_daily_portfolio[index_spy] )
RETURN IF ( HASONEVALUE ( fact_daily_portfolio[price_date] ), DIVIDE ( TodayIndex, StartIndex ) * 100 )

Check DAX (Portfolio) =
SWITCH ( SELECTEDVALUE ( analysis_summary[metric_key] ),
    "total_return", [Total Return],
    "annualized_return", [Annualized Return],
    "annualized_volatility", [Annualized Volatility],
    "avg_rf_annual", [Avg Risk-Free Rate],
    "sharpe_ratio", [Sharpe Ratio],
    "max_drawdown", [Max Drawdown],
    "excess_return_annualized", [Excess Return Annualized],
    "excess_return_total", [Excess Return Total],
    "ending_market_value", [Latest Market Value],
    "net_contributions", [Net Contributions],
    "return_days", [Return Days] )

Check DAX (SPY) =
SWITCH ( SELECTEDVALUE ( analysis_summary[metric_key] ),
    "total_return", [Total Return SPY],
    "annualized_return", [Annualized Return SPY],
    "annualized_volatility", [Annualized Volatility SPY],
    "avg_rf_annual", [Avg Risk-Free Rate],
    "sharpe_ratio", [Sharpe Ratio SPY],
    "max_drawdown", [Max Drawdown SPY],
    "return_days", [Return Days] )

Check Stored (Portfolio) = SELECTEDVALUE ( analysis_summary[portfolio_value] )

Check Stored (SPY) = SELECTEDVALUE ( analysis_summary[spy_value] )

Check Diff (Portfolio) =
VAR DaxValue = [Check DAX (Portfolio)]
RETURN IF ( NOT ISBLANK ( DaxValue ), FORMAT ( DaxValue - [Check Stored (Portfolio)], "0.00E+00" ) )

Check Diff (SPY) =
VAR DaxValue = [Check DAX (SPY)]
RETURN IF ( NOT ISBLANK ( DaxValue ) && NOT ISBLANK ( [Check Stored (SPY)] ),
    FORMAT ( DaxValue - [Check Stored (SPY)], "0.00E+00" ) )

Check Status =
VAR Tol = IF ( SELECTEDVALUE ( analysis_summary[unit] ) = "USD", 0.000001, 0.000000001 )
VAR DaxP = [Check DAX (Portfolio)]
VAR StoredP = [Check Stored (Portfolio)]
VAR DaxS = [Check DAX (SPY)]
VAR StoredS = [Check Stored (SPY)]
VAR OkP = ISBLANK ( DaxP ) || ABS ( DaxP - StoredP ) <= Tol
VAR OkS = ISBLANK ( DaxS ) || ISBLANK ( StoredS ) || ABS ( DaxS - StoredS ) <= Tol
RETURN IF ( ISBLANK ( DaxP ) && ISBLANK ( DaxS ), "not checked (stored only)",
    IF ( OkP && OkS, "PASS", "FAIL" ) )

Check Total Return 2024 = CALCULATE ( [Total Return], dim_date[year] = 2024 )

Check Contribution Diff (Full) = FORMAT ( [Return Contribution] - [Total Return], "0.00E+00" )

Check Contribution Diff (2024) =
FORMAT ( CALCULATE ( [Return Contribution] - [Total Return], dim_date[year] = 2024 ), "0.00E+00" )
```
