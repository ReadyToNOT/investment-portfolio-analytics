# Backtest rules (Stage 6, business question 5)

**Status:** APPROVED v0.3, 2026-10-19. Rules approved by Jacob before any backtest result was seen.
**Question:** Would a simple rebalancing rule have improved results for the sample portfolio?

Sample portfolio, educational project, not investment advice.

This file fixes every rule, parameter, cost and metric in advance. `src/backtest.py` must implement exactly what is written here.

---

## 1. Anti-tuning rules

- Every parameter is fixed now. Each strategy has **one** parameter set: no grid search, no second "daily signal" variant.
- The headline cost is **10 basis points** (0.10 of one percent of traded value). The 0 and 25 bp runs are a sensitivity table only and are never used to choose a strategy or a parameter.
- After results are seen, a rule may change **only** to fix a correctness bug. Every change goes into section 10 with the date, the change, the reason and whether results had been seen.

**Plain language:** a backtest replays history with fixed rules. Changing the rules after seeing which version "wins" fits the rules to the past, and the result then says little about the rules themselves.

---

## 2. Common setup

| Item | Rule |
|---|---|
| Universe | The 12 rows of `dim_security` with `role = 'HOLDING'`, sorted by ticker. SPY (`role = 'BENCHMARK'`) is never traded. |
| Target weights | `dim_security.target_weight`, read at runtime. Must be 12 rows summing to 1 (1e-12). |
| Base day | 2023-11-01 (`config.PORTFOLIO_START`). Index = 100 for every strategy. |
| Last day | The last date in `fact_daily_portfolio` (currently 2026-10-16): 742 trading days, 741 return days. |
| Starting capital | 100,000 dollars in cash just before the base-day close. It buys the starting positions at the base-day close, and the purchase cost is paid from the 100,000. |
| Base-day value | The value after the purchase and its cost, about 99,900 dollars for S1 and S2. Index = 100 is set on this value, so the initial cost lowers the dollar value but not the return series. It still counts in total costs paid. |
| Prices | `adj_close_price` for valuing and trading: total return, with dividends reinvested in the same holding. |
| Position units | Positions are held in "adjusted units" (value / adj_close). The `units` column in the trades table is in these units, **not** real share counts. |
| Execution | At the close of the trade date, at that day's adj_close. |
| Frictions | Fractional units, no minimum trade size, no taxes, no slippage beyond the cost rate, no borrowing, no shorting. |
| Cash | Only S3 holds cash. On return day t: cash_t = cash_(t-1) x (1 + rf_daily_t), with `rf_daily` read from `fact_daily_portfolio` (so the Stage 5 convention is reused). |

**Why the initial cost is kept out of the return series:** the base day has no return, so its cost can only enter by breaking "index = 100 on the base day". It is also almost the same for every strategy and has nothing to do with rebalancing. ACTUAL and SPY carry no costs at all, so leaving it out keeps all five lines comparable.

### Order of operations on each day t after the base day
1. Mark each position to the close of t (units x adj_close_t) and grow cash by rf_daily_t.
2. Pre-trade value: V_pre = sum of position values + cash.
3. If t is a trade date for the strategy, trade to the new weights and pay costs (section 4).
4. Record the post-trade value V_t. Daily return r_t = V_t / V_(t-1) - 1, so the cost paid on day t lowers r_t.

### Month-end trade dates (correctness fix found while reading Stage 4 code)
`sql/04_load_model.sql` flags the **last trading day present in the data** for each month. In the last, incomplete month, that is simply the last price date. As a result `dim_date.is_month_end_trading_day` is TRUE on 2026-10-16, which is not a real month-end. Checked against `data/raw/prices_daily.csv`: 36 dates after the base day are flagged, and the last one is 2026-10-16.

**Rule:** the trade dates are the flagged dates strictly after the base day, **excluding** the last price date unless it is the last NYSE trading day of its calendar month. That test uses weekdays minus `config.NYSE_HOLIDAYS`. Expected: 35 trade dates, from 2023-11-30 to 2026-09-30.
Stage 4 is left unchanged. The flag only matters for this backtest, and the Power BI notes will say what the flag means.

---

## 3. Strategies

### S1_BUY_HOLD: Buy and hold
- Buy at target weights on the base day. Never trade again, so weights drift with prices.

### S2_MONTHLY: Monthly rebalance
- On each of the 35 trade dates (section 2), every holding goes back to target_weight x post-trade value.
- Units do not change between trade dates.

### S3_MA_50_200: 50/200-day moving-average filter, checked monthly
- **Signal** for holding i at the close of day s: ON if SMA50_i(s) > SMA200_i(s). These are simple averages of adj_close over the last 50 and 200 trading days **ending at s, inclusive**. A tie counts as OFF. The full price history from 2022-12-01 is used for the averages.
- **Execution dates:** the base day plus the same 35 dates as S2 (36 in total).
- **Signal date:** the trading day **immediately before** each execution date. For the base day this is 2023-10-31, which has 230 trading days of history (at least 200 are needed).
- **At each execution date:** a holding with signal ON goes to target_weight x post-trade value. A holding with signal OFF goes to 0. Cash = (sum of OFF target weights) x post-trade value.
- **Re-entry:** a holding that switches back ON returns to its target weight of **current total value**. On every execution date, all slices (the ON holdings and the cash) are reset, so S3 = S2 + a trend filter.
- Between execution dates, units and the cash balance stay fixed, except that cash earns interest.

**Why monthly, not daily (decided before results):**
1. It isolates the filter: S2 and S3 trade on the same dates, so any difference comes from the signal, not from trading more often.
2. It cuts whipsaw: a daily 50/200 crossover can flip back and forth near the crossing point, paying costs on every flip.
3. Published trend-filter rules usually check monthly.
4. It keeps the result checkable: 36 decisions instead of about 740.

Daily evaluation is not run as a second variant. Running it and reporting whichever looks better would be tuning.

**Why 50/200:** it is the conventional "golden cross / death cross" pair, chosen without looking at this data.

**Look-ahead rule:** the decision on execution date t uses only adj_close data up to and including the previous trading day (t-1).

### References (no trading and no costs, copied from Stage 5)
- **ACTUAL:** from `fact_daily_portfolio` (index_p, r_p, dd_p, market_value). This is a time-weighted return. The real portfolio had top-ups at non-target weights and one sale, so it is a reference, not a like-for-like strategy.
- **SPY:** from `fact_daily_portfolio` (index_spy, r_spy, dd_spy).

---

## 4. Cost model

- cost = c x |traded value| for every trade, with c = 0.0010 at the headline cost. The cost is paid out of the portfolio.
- Moving money into or out of cash is not a trade and costs nothing. Only the security legs are charged.
- **Hitting the targets exactly after costs.** The post-trade value V' depends on the cost, and the cost depends on V'. This is solved by fixed-point iteration (repeat the calculation, feeding each answer back in, until it stops changing):

      V' = V_pre - c x sum over i of | w_i x V' - units_i x P_i |

  Start with V' = V_pre. Stop when the change is below 1e-10 dollars. Raise an error after 100 iterations. With c = 0.001 it converges in a few steps.
  Then units_i = w_i x V' / P_i and cash = w_cash x V', so post-trade weights equal the targets up to rounding.
- On the base day every trade is a buy from cash, so this has a closed form: V' = 100,000 / (1 + c x (1 - w_cash)). For S1 and S2 that is 100,000 / 1.001.
- A trade row is written only when |traded value| > 1e-9 dollars. For example, an S3 holding that stays OFF writes no row.
- The S3 signals do not depend on c, so the 0, 10 and 25 bp runs make identical decisions.

---

## 5. Metrics (definitions identical to `analysis.build_summary`)

All metrics come from the post-trade daily series. N = 741 return days.

| Metric | Definition |
|---|---|
| Total return | index_last / 100 - 1 |
| Annualized return | (1 + total)^(252 / N) - 1 |
| Annualized volatility | sample std (ddof 1) of the N daily returns x sqrt(252) |
| Average risk-free rate | (1 + mean rf_daily over return days)^252 - 1. This is the same number as `analysis_summary.avg_rf_annual`. |
| Sharpe ratio | (annualized return - average risk-free rate) / annualized volatility |
| Max drawdown | min of (index / running max of index - 1) |
| Beta vs SPY | cov(r_s - rf, r_spy - rf) / var(r_spy - rf), full period (**excess returns**, as in Stage 5). Raw-return beta is also stored, for comparison only. |
| Worst drawdown episode | The rank-1 episode from `analysis.drawdown_episodes()`: peak, trough, recovery date (NULL if not recovered), depth, trading days. |
| Number of trades | Trade rows, both including and excluding the base-day purchase. |
| Turnover (annualized) | (sum of traded value excluding the base day) / (average daily value over 742 days) x (252 / N). This counts buys and sells, as in the kickoff spec. |
| Total costs paid | Sum of cost, including the base-day purchase. |
| Average cash weight | Mean over the 742 days of cash / V (post-trade). This is 0 for S1 and S2. |

---

## 6. Output tables (`sql/09_create_backtest_tables.sql`)

Every date column references `dim_date(date_key)`, and ticker columns reference `dim_security(ticker)`. Column names follow Stage 5 (`price_date`).

- **dim_strategy** (5 rows): strategy_code (PK), strategy_name, sort_order, is_reference, description. Power BI uses it for legend labels, line order and a slicer. A small table is better than a CHECK constraint because Power BI needs the labels and the sort order anyway.
- **fact_backtest_daily**: one row per strategy per trading day, **headline cost only**, references included. 5 x 742 = 3,710 rows.
  Columns: strategy_code, price_date, value, daily_return (NULL on the base day), index_value, cum_return, drawdown, cash_weight, cost_paid.
  For the references, value = market_value for ACTUAL and NULL for SPY; cash_weight and cost_paid are NULL.
- **fact_backtest_trades**: S1 to S3 at the headline cost. Columns: strategy_code, price_date, ticker, side (BUY or SELL), units, price, traded_value (> 0), cost (>= 0).
- **fact_backtest_summary**, in long format (one row per strategy, cost level and metric), which Power BI filters easily: strategy_code, cost_bps (0, 10, 25), is_headline, metric_key, metric_name, value, unit, definition, sort_order. The references appear once each, with cost_bps = 0 and is_headline = TRUE.
- **fact_backtest_worst_drawdown**: one row per strategy at the headline cost: strategy_code, peak_date, trough_date, recovery_date, depth, days_to_trough, days_peak_to_recovery, recovered. Dates do not fit the numeric `value` column of the summary table, so they get their own 5-row table.

---

## 7. Checks (`src/check_backtest.py`)

Run on tables read back from PostgreSQL. The 0 and 25 bp runs are not stored day by day, so checks on them use the in-memory simulations.

| ID | Check | Tolerance |
|---|---|---|
| B01 | Target weights: 12 rows, sum = 1 | 1e-12 |
| B02 | Row counts: daily = 5 x 742, one row per strategy per day, no duplicate trade rows | exact |
| B03 | Index = 100 on the base day for all 5 | 1e-12 |
| B04 | Value = positions + cash, every strategy and day. At 10 bp the positions are rebuilt from the stored trade rows; at 0 and 25 bp the in-memory units are used | 1e-6 dollars |
| B05 | S1 at 0 bp: r_t = sum of w_(i,t-1) x r_(i,t) (Stage 5 logic) | 1e-12 |
| B06 | S1 units constant after the base day | exact |
| B07 | S2 post-trade weights = targets on every trade date | 1e-9 |
| B08 | S2 units unchanged between trade dates | exact |
| B09 | S2 at 0 bp: V_pre = V_post on every trade date | 1e-9 |
| B10 | Sum of cost = c x sum of traded value, per strategy and cost level | 1e-9 |
| B11 | V' + cost = V_pre on every trade date (base day included) | 1e-9 |
| B12 | S3 look-ahead (a): signals recomputed from prices cut off at t-1 equal the stored decisions | exact |
| B13 | S3 look-ahead (b): changing every adj_close on or after each execution date leaves that date's decision unchanged | exact |
| B14 | S3 first signal date has at least 200 trading days of history | exact |
| B15 | S3 cash weight in [0, 1]; post-trade weights equal the target or 0 | 1e-9 |
| B16 | Identical decisions at 0, 10 and 25 bp | exact |
| B17 | Summary metrics recomputed with numpy from the read-back daily table equal the stored values; beta via numpy.polyfit; worst-drawdown depth = max drawdown | 1e-12 (beta 1e-9) |
| B18 | Drawdown <= 0 everywhere | exact |
| B19 | No NULLs except the documented ones | exact |
| B20 | ACTUAL and SPY rows equal `fact_daily_portfolio` | 1e-12 |
| B21 | Trade dates = 35, all real month-ends, and 2026-10-16 is not among them | exact |
| B22 | ACTUAL and SPY summary values equal `analysis_summary` (total return, volatility, Sharpe, max drawdown, beta) | 1e-12 |

**Hand check (Jacob, `docs/reconciliation.md`):** S2 at 10 bp, using the adj_close values in `data/raw/prices_daily.csv`:
1. Base-day value V' = 100,000 / 1.001. Units_i = w_i x V' / adj_close_i(2023-11-01).
2. V_pre on 2023-11-30 = sum of units_i x adj_close_i(2023-11-30).
3. Each post-trade value = w_i x V' (stored in `fact_backtest_trades` through the units).
4. Cost = 0.001 x sum of |traded value|.
5. V' + cost = V_pre.

None of these steps requires solving the fixed point by hand.

---

## 8. Expected values (not results; the code will confirm them)

- S2 trade dates: 35. S3 execution dates: 36.
- S1 trade rows: 12. S2 trade rows: at most 12 + 35 x 12 = 432.
- Base-day cost at 10 bp for S1 and S2: 100,000 - 100,000 / 1.001 = 99.90 dollars. S3 is the same or lower (OFF slices are not bought).

---

## 9. Limitations (stated, not fixed)

- **Survivorship and hindsight:** the 12 holdings were chosen today, knowing they still exist and are large.
- **One short path:** about three years of one market history. Differences between strategies may be noise. No significance test is run.
- **Simplified costs and execution:** a flat basis-point cost, fills at the close, no taxes (rebalancing in a taxable account would realize gains), no market impact.
- **adj_close restatement:** yfinance back-adjusts history when new dividends arrive, so a re-download can shift historical adj_close levels slightly. A hand check must use the same CSV snapshot as the run.
- **Calendar choice:** month-end rebalancing is a convention. Other days of the month would give somewhat different numbers.
- Fictional educational portfolio. Nothing here is investment advice.

---

## 10. Change log

| Date | Version | Change | Reason | Results seen? |
|---|---|---|---|---|
| 2026-10-19 | 0.1 | Initial draft | n/a | No |
| 2026-10-19 | 0.2 | Holding filter is role = 'HOLDING'. Beta uses excess returns. Average rf uses the Stage 5 formula. The initial cost is paid from the 100,000. Month-end rule excludes the partial last month. Summary table is long format plus a worst-drawdown table. Turnover counts buys and sells. Added B22. | Matched to the Stage 5 code after reading analysis.py and sql/04; one data issue found in dim_date | No |
| 2026-10-19 | 0.3 | Approved. B04 and B17 wording made more specific (B04 rebuilds positions from stored trades; B17 beta uses polyfit with tolerance 1e-9, as in Stage 5 check A15). No rule, parameter or cost changed. | Checks written to be independent of the simulation code | No |
