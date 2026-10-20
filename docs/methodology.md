# Methodology — Stage 5 Analysis Metrics

Status: approved 2026-10-19, before any analysis code ran, so the
definitions were fixed before results were seen. Sections 13 and 14 were
then updated to list the exact columns and checks the code implements. No result numbers appear in
this file; the one worked example in section 4 uses a made-up rate.

Sample portfolio, educational only. Not investment advice.

---

## 1. Conventions used everywhere

| Item | Definition |
|---|---|
| Trading days | Dates with a row in `fact_prices` (equivalently `dim_date.is_trading_day`). "t-1" always means the previous **trading** day, never the previous calendar day. |
| Portfolio period | Trading days from 2023-11-01 (base day) to the last price date. |
| Base day | 2023-11-01. Index = 100, cumulative return = 0, drawdown = 0. It has **no** return, weight-at-previous-close or risk-free rate (all NULL). |
| Return days | Portfolio-period trading days after the base day. N = number of return days. All statistics (vol, beta, correlation, Sharpe) use return days only. |
| Returns | Simple (not log) returns from `adj_close_price`, which includes dividends. |
| Market value | `shares_held x close_price` from `vw_daily_holdings` (actual close, no dividends, no cash). Value and total return are not expected to reconcile exactly (dividends are in returns but not in value). |
| Annualization | 252 trading days. Volatility x sqrt(252); returns compounded to the power 252/N. |
| Std deviation | Sample standard deviation (ddof = 1, divide by n - 1) everywhere. This matches DAX `STDEV.S`. |
| Units | All rates and returns stored as fractions (0.0123 = 1.23 percent). Power BI formats them as percentages. |

---

## 2. Holding and benchmark daily returns (a)

**Formula:** `r(i,t) = adj_close(i,t) / adj_close(i,t-1) - 1`

**Inputs:** `fact_prices.adj_close_price` for the 12 holdings and SPY.

**First valid date:** first return day (the trading day after 2023-11-01).
r on that day uses the 2023-11-01 adj close, which exists for all 13 tickers.

**Edge cases:**
- No splits occur in the window (verified Stage 3), and adj_close handles
  dividends, so no further adjustment is needed.
- A holding is only included in the portfolio return on days it was held at
  the previous close (w(i,t-1) > 0). Returns of all 13 tickers are still
  computed on every return day for correlation and beta.

---

## 3. Time-weighted portfolio return (b) and the price-only cross-check (c)

**Start-of-day weights:**
`w(i,t-1) = MV(i,t-1) / sum over j of MV(j,t-1)`, where MV(i,t-1) is
`vw_daily_holdings.market_value` at the previous close, **after** that day's
trades (the view already measures positions after the close).

**Portfolio daily return:** `r_p(t) = sum over i of w(i,t-1) x r(i,t)`

**Cumulative and index:**
`G(t) = product over return days s <= t of (1 + r_p(s))`, with G(base) = 1
`cum_p(t) = G(t) - 1`, `index_p(t) = 100 x G(t)`.
SPY: same formulas with r_spy(t). Because SPY is a single asset,
`cum_spy(T) = adj_close(SPY,T) / adj_close(SPY,base) - 1` exactly.

**Why this removes cash flows:** a trade at the close of day t changes MV and
weights from t onward but only affects returns from t+1, so new money never
shows up as performance.

**Why weights x adjusted returns is a good approximation of true TWR:** the
weights come from unadjusted market value while returns use adjusted prices.
On ex-dividend days this treats the dividend as reinvested in the same
holding at that day's close. That is the standard total-return convention
and is stated on the Notes page.

**Price-only cross-check (validation only, not stored as a metric):**
`(MV(t) - NC(t)) / MV(t-1) - 1  =  sum over i of w(i,t-1) x [close(i,t)/close(i,t-1) - 1]`
where NC(t) is the net contribution on day t (positive buy, negative sale).
Both sides equal `sum shares_held(i,t-1) x close(i,t) / MV(t-1) - 1`, so they
must match to 1e-9 on every return day. This proves the weights and cash
flows line up with the view.

**First valid date:** first return day. **Edge cases:** none expected; MV(t-1)
is always > 0 because the portfolio holds positions every day.

---

## 4. Risk-free rate from DTB3 (d)

**Source:** FRED series DTB3, the 3-month Treasury bill secondary market rate
on a discount basis, published by the Federal Reserve Board in the H.15
release. Units: percent per year.

**Why it needs converting:** a discount rate is quoted on face value with a
360-day year, so it understates the return actually earned on the price paid.
Treasury's own price formula is `P = 100 x (1 - d x t / 360)`.

**Step 1 — discount rate to bond-equivalent (investment) yield:**

    d    = dtb3_discount_pct / 100
    BEY  = 365 x d / (360 - d x t),   t = 91 days

This is the formula Treasury uses for the investment rate of bills of
182 days or less, and the same formula behind Excel's `TBILLEQ`. t = 91 is
the standard term of a 13-week (3-month) bill; the actual days to maturity
of the quoted bill vary by a day or two, which changes the yield negligibly.

**Step 2 — annual yield to a daily rate per trading day:**

    rf_daily = (1 + BEY) ^ (1/252) - 1

Justification: we annualize returns geometrically with 252 days, so the
risk-free rate uses the same convention; compounding rf_daily over 252
trading days gives back BEY. The simpler BEY / 252 differs only slightly.

Worked example (made-up rate, not our data): d = 3.60 percent gives
BEY = 0.036835 and rf_daily = 0.00014355 (BEY / 252 would be 0.00014617).

**Which day's rate applies to day t (agreeing with your proposal):**
the return on day t is earned from the close of t-1 to the close of t, so it
uses the rate known at the close of t-1:

    rf_daily(t) = conversion of the last non-blank DTB3 value on or before t-1

The H.15 rate for a date describes that date's market, so the t-1 value is
the rate an investor could have locked in when the holding period started.
Forward-fill handles the 43 blank days (holidays and missing quotes);
check M28 guarantees no gap longer than 7 days.

**Coverage:** the last return day (2026-10-16) uses the 2026-10-15 rate,
which exists, so no rate past the DTB3 end date is needed.

**Edge cases:**
- Base day: rf_daily is NULL (there is no return to compare it with).
- Weekends/holidays: a Monday return covers 3 calendar days but gets one
  day of rf. This is consistent with counting 252 trading days per year.

**Stored:** `rf_daily` on every return day; also `rf_annual` (BEY) for display.

---

## 5. Rolling volatility (e)

**Formula:** `vol_W(t) = stdev(r(t-W+1) ... r(t), ddof = 1) x sqrt(252)`,
W = 30 and 90, for the portfolio and SPY. Raw returns (not excess).

**First valid date:** the W-th return day. The window never reaches back
before the base day (no pre-period returns are used), so the series starts
fresh at the portfolio start.

**NULL count in fact_daily_portfolio:** W - 1 return days plus the base day,
so W rows in total are NULL.

---

## 6. Beta vs SPY (f)

**Full period:** `beta_i = cov(x_i, x_spy) / var(x_spy)` over all return
days, for the portfolio and each holding (sample cov and var, both ddof = 1,
so the n - 1 cancels).

**Rolling 90-day portfolio beta:** same formula over the trailing 90 return
days. First valid date and NULL count as in section 5.

**Raw or excess returns: excess returns**, `x = r - rf_daily`.
Reason: beta in the CAPM is defined on excess returns, and the Sharpe ratio
already uses excess returns, so one convention covers all risk-adjusted
numbers. In practice the difference is tiny because rf_daily barely moves
day to day; the script also prints the raw-return beta for information.

**Holdings bought after the start:** not applicable here, every holding is
held from 2023-11-01. If that ever changed, a holding's beta would use only
days it existed.

**Validation:** equals the slope of `numpy.polyfit(x_spy, x_i, 1)` (a
least-squares line), to 1e-9.

---

## 7. Correlation matrix (g)

**Formula:** Pearson correlation of raw daily returns over all return days,
for the 12 holdings + SPY.

**Stored in long format:** one row per ordered pair (ticker_a, ticker_b),
13 x 13 = 169 rows, including the diagonal (= 1) and both orderings, so the
matrix is symmetric. Columns `sort_a` / `sort_b` give a display order
(grouped by sector, SPY last) so Power BI shows a tidy matrix.

---

## 8. Drawdowns (h)

**Series:** `drawdown(t) = index(t) / max(index(base..t)) - 1`, for the
portfolio and SPY. Always <= 0; equals 0 on the base day and at new highs.

**Episodes (one row per drawdown):**
- *Peak date*: the last day the index was at its running maximum before it
  fell below it.
- *Trough date*: the day with the lowest index between peak and recovery
  (or the last date, if not recovered). Ties: the first such day.
- *Recovery date*: the first day after the trough with index >= the peak
  index. NULL if not yet recovered.
- *Depth*: `index(trough) / index(peak) - 1` (negative).
- *Days peak to trough*, *days trough to recovery*: counts of trading days
  (by position in the trading calendar). Recovery days NULL if not recovered.
- *Recovered flag*: true/false.
- *Rank*: 1 = deepest, per series.

**Edge cases:** an episode still open on the last date is kept with
recovered = false. Every dip, even 1 day, creates an episode, so the table
will have many shallow rows; the dashboard filters by rank (e.g. top 5) or
by a depth threshold. Max drawdown = min(drawdown) = depth of rank 1.

---

## 9. Return contribution by holding and sector (i)

**Daily contribution:** `c(i,t) = w(i,t-1) x r(i,t)`, so `sum over i of c(i,t) = r_p(t)`.

**Linked contribution:** `lc(i,t) = c(i,t) x G(t-1)`.
Summed over all holdings and the full period this telescopes exactly:
`sum over t of r_p(t) x G(t-1) = sum of [G(t) - G(t-1)] = G(T) - 1 = cum_p(T)`.

**Sub-period problem and the fix:** for a period that starts on day s after
the base day, the sum of lc over [s, e] equals `G(e) - G(s-1)`, not the
period's own return `G(e)/G(s-1) - 1`. Dividing by G(s-1) fixes it exactly:

    period contribution(i) = sum over t in [s,e] of lc(i,t) / G(s-1)

which sums over holdings to `G(e)/G(s-1) - 1`, the exact compounded period
return. So fact_daily_portfolio stores `growth_prev = G(t-1)`, and the DAX
measure divides by `growth_prev` on the first selected date. Any date range
in the dashboard then reconciles exactly.

Trade-off that remains: the split between holdings for a sub-period depends
on returns earned earlier (G scales all holdings equally on a given day, so
it does not favour any holding, but later days carry more weight in dollar
terms). This is a property of all simple linking methods and is stated on
the Notes page.

**Sector:** sum of its holdings (via `dim_security.sector` in Power BI, no
separate table).

---

## 10. Risk contribution (j)

Two methods, stored in one table with a `method` column. Both sum to exactly
100 percent by construction.

**Method A — historical (primary, answers "what drove risk"):**

    RC_A(i) = cov(c(i,t), r_p(t)) / var(r_p)   over all return days

Because `sum of c(i,t) = r_p(t)` every day, the covariances add up to var(r_p)
exactly, using the **actual daily weights** (including trades and drift). No
choice between latest and average weights is needed, and it is consistent
with the return contribution in section 9.

**Method B — current (answers "what drives risk today"):**

    RC_B(i) = w_T(i) x (Sigma w_T)(i) / (w_T' Sigma w_T)

where w_T are the end-of-day weights on the last date and Sigma is the
sample covariance matrix of the 12 holdings' daily returns over the last
252 return days (one year: long enough to be stable, short enough to be
current). This is the standard Euler decomposition of the variance of a
fixed-weight portfolio.

**Sector:** sum of its holdings, in Power BI.

---

## 11. Concentration (k)

Per portfolio trading day t (including the base day), using end-of-day
weights after trades, `w(i,t) = vw_daily_holdings.actual_weight`:

- `HHI(t) = sum of w(i,t)^2`
- `effective_n(t) = 1 / HHI(t)`
- `top5_share(t)` = sum of the 5 largest weights
- `max_abs_drift(t) = max over i of |w(i,t) - target_weight(i)|`, plus the
  ticker where it occurs.

Per-holding drift stays a DAX measure.

---

## 12. Summary metrics (l)

Full period (base day to last date), N = number of return days.

| Metric | Formula | SPY row |
|---|---|---|
| Total return | G(T) - 1 | same with SPY |
| Annualized return | (1 + total)^(252/N) - 1 | same |
| Annualized volatility | stdev(r, ddof 1) x sqrt(252) | same |
| Average risk-free rate (annual) | (1 + mean(rf_daily))^252 - 1 | same value |
| Sharpe ratio | (annualized return - average rf annual) / annualized volatility | same |
| Max drawdown | min(drawdown) | same |
| Beta | section 6 | 1 by definition |
| Excess return | portfolio annualized return - SPY annualized return | NULL |
| Total excess return | portfolio total - SPY total | NULL |
| Return days N, start date, end date | counts | same |

The Sharpe definition follows the project plan ((annualized return minus
average risk-free rate) divided by annualized volatility), so the DAX
measure can reproduce it. Stage 7 DAX measures must match these values.

---

## 13. Output tables

Created by `sql/08_create_analysis_tables.sql`. Every date column references
`dim_date.date_key` and every ticker column references `dim_security.ticker`
(foreign keys).

| Table | Grain | Columns |
|---|---|---|
| fact_daily_portfolio | one row per portfolio trading day (base day included) | price_date (PK), is_base_day, market_value, net_contribution, r_p, r_spy, rf_rate_date, rf_annual, rf_daily, growth_prev, index_p, index_spy, cum_p, cum_spy, dd_p, dd_spy, vol30_p, vol90_p, vol30_spy, vol90_spy, beta90_p, hhi, effective_n, top5_share, max_abs_drift, max_drift_ticker |
| fact_daily_holding_returns | holding x return day | price_date + ticker (PK), r, w_prev, contrib, linked_contrib |
| fact_correlation | ticker pair (169 rows) | ticker_a + ticker_b (PK), correlation, sort_a, sort_b |
| fact_drawdown_episodes | episode | series + episode_no (PK), peak_date, trough_date, recovery_date, depth, days_to_trough, days_to_recover, days_peak_to_recovery, recovered, depth_rank |
| fact_risk_contribution | method x holding | method + ticker (PK), weight_used, risk_contribution, window_start, window_end, return_days |
| fact_holding_beta | holding | ticker (PK), beta_excess, beta_raw |
| analysis_summary | metric | metric_key (PK), metric_name, portfolio_value, spy_value, unit, definition, period_start, period_end, sort_order |

Notes:
- `rf_rate_date` records which DTB3 date each day's rate came from, so the
  forward-fill can be audited.
- `sort_a` / `sort_b` order the correlation matrix by sector (alphabetical),
  then ticker, with SPY last.
- Power BI can only have one active relationship between two tables. Tables
  with several date or ticker columns (episodes, correlation, risk
  contribution) keep one active relationship; Stage 7 decides which.
- `sql/03_create_model.sql` drops dim_date and dim_security with CASCADE,
  which also removes the foreign keys on these tables. Always run
  `build_analysis.py` after `build_model.py`; it re-creates everything.

---

## 14. Validation checks (Python, PASS/FAIL, exit 0/1)

Run by `src/build_analysis.py` (code in `src/check_analysis.py`) on the tables
**read back from PostgreSQL**, so they test what Power BI will see. Where
possible a check recomputes the number a different way.

| ID | Check | Tolerance |
|---|---|---|
| A01 | fact_daily_portfolio rows = portfolio trading days, same dates | exact |
| A02 | fact_daily_holding_returns rows = 12 x N | exact |
| A03 | Base day: index 100, cum 0, drawdown 0, no r_p, no rf, exactly one base row | exact |
| A04 | Weights at previous close sum to 1 on every return day | 1e-12 |
| A05 | Sum of contributions = r_p on every return day | 1e-12 |
| A06 | index_p = 100 x product(1 + r_p); growth_prev = G(t-1) | 1e-9 |
| A07 | Sum of linked contributions = cumulative portfolio return | 1e-9 |
| A08 | Rescaled linked contributions = each calendar year's compounded return | 1e-9 |
| A09 | Price-only cross-check (section 3) on every return day | 1e-9 |
| A10 | Stored holding returns = adj_close ratio from fact_prices | 1e-12 |
| A11 | SPY cumulative = last adj close / base adj close - 1 | 1e-9 |
| A12 | Drawdown <= 0; max drawdown = min(drawdown) = rank-1 depth; recovery flags consistent, at most one open episode and it is the last | 1e-12 |
| A13 | Rolling vol and beta: NULL count = W; first value on the W-th return day | exact |
| A14 | Last vol30_p = numpy std of the last 30 returns x sqrt(252) | 1e-12 |
| A15 | Full-period beta (portfolio and 12 holdings) = numpy.polyfit slope | 1e-9 |
| A16 | Last rolling 90-day beta = polyfit slope over the last 90 return days | 1e-9 |
| A17 | Correlation: 169 rows, diagonal 1, symmetric | 1e-12 |
| A18 | rf_daily present on every return day, 0 < rf_daily < 0.001, DTB3 source date 0-7 days before t-1 | exact |
| A19 | rf_daily = conversion of the DTB3 value on rf_rate_date | 1e-15 |
| A20 | Risk contributions sum to 1 for each method, 12 rows each | 1e-9 |
| A21 | HHI and effective N match the view's actual_weight; top-5 share in range | 1e-12 |
| A22 | Summary metrics agree with the daily table | 1e-12 |

Foreign keys, primary keys and CHECK constraints in sql/08 are enforced by
PostgreSQL at load time (a violation aborts the whole transaction).

Plus the hand check in docs/reconciliation.md (portfolio return on
2024-05-02, done by you with a calculator).

## Sources

- FRED, DTB3 series page (discount basis, H.15): https://fred.stlouisfed.org/series/DTB3
- TreasuryDirect, "Price, Yield and Rate Calculations for a Treasury Bill": https://www.treasurydirect.gov/instit/annceresult/press/preanre/2004/ofcalc6decbill.pdf
- Microsoft, TBILLEQ function: https://support.microsoft.com/en-US/excel/functions/tbilleq-function
