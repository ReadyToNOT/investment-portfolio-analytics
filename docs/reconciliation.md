# Hand reconciliation: one holding (AAPL)

Purpose: prove, with a calculator and the raw files, that `vw_daily_holdings`
gives the right shares and market value. AAPL is used because it is the only
holding with a sale (T019: SELL 20 shares on 2025-08-01), so the check covers
both buying and selling.

Sample portfolio, educational project, not investment advice.

## Method

1. **Shares held.** Open `data/processed/transactions.csv`. For each date below,
   add every AAPL BUY and subtract every AAPL SELL with `trade_date` on or before it.
2. **Close.** Open `data/raw/prices_daily.csv` in Excel, filter `ticker` = AAPL,
   and read the `close` column (the actual close, not `adj_close`) for each date.
3. **Market value** = shares held × close, rounded to cents.
4. Run `sql/07_reconcile_holding.sql` in pgAdmin and copy `value_in_view`.
5. The difference must be $0.00.

## Results

Filled in by hand on: 2026-10-22

| Date | Trades counted | Shares held | Close (from CSV) | Shares × close (by hand) | Value in view | Difference |
|---|---|---|---|---|---|---|
| 2023-11-01 (first buy) | T002 | 63 | 173.97000122070312 | 10,960.11 | 10,960.11 | $0.00 |
| 2025-07-31 (day before sale) | T002 | 63 | 207.57000732421875 | 13,076.91 | 13,076.91 | $0.00 |
| 2025-08-01 (sale day) | T002, T019 | 43 | 202.3800048828125 | 8,702.34 | 8,702.34 | $0.00 |
| last price date: 2026-10-16 | T002, T019 | 43 | 343.4599914550781 | 14,768.78 | 14,768.78 | $0.00 |

## Notes

- On a trade date the position already includes that day's trade, because the
  sample assumes trades happen at the closing price (see `data/processed/README.md`).
- Market value uses the unadjusted `close`. Using `adj_close` here would be wrong:
  adjusted prices are lowered for later dividends, so they understate what the
  shares were actually worth on that day. Adjusted prices are for returns (Stage 5).
- `src/reconcile_holdings.py` repeats this check automatically for every holding
  on every day (pandas from the CSVs vs the SQL view).

---

# Hand check 2 (Stage 5): portfolio return on 2024-05-02

Purpose: prove, with a calculator or Excel and the raw files, that the
time-weighted portfolio return in `fact_daily_portfolio` is right on the day
after a trade date. 2024-05-01 had two top-ups (T013 MSFT +10, T014 XLF +100),
so this also proves that trades at the close of day t only change weights
from day t+1 (methodology.md section 3).

## Method

1. **Shares at the 2024-05-01 close (after that day's trades).** From
   `data/processed/transactions.csv`, add every trade on or before 2024-05-01.
   The column below is filled in from the trade log (T001-T014).
2. **Weights.** From `data/raw/prices_daily.csv`, take the `close` on
   2024-05-01. Value = shares x close. Weight = value / sum of the 12 values.
3. **Returns.** Take `adj_close` on 2024-05-01 and 2024-05-02.
   r = adj_close(05-02) / adj_close(05-01) - 1.
4. **Portfolio return** = sum of weight x r over the 12 holdings.
5. Compare with the stored value. In pgAdmin run:
   `SELECT r_p FROM fact_daily_portfolio WHERE price_date = DATE '2024-05-02';`
   The two must agree to at least 8 decimal places (Excel shows about 15
   significant digits).

## Results

Filled in by hand on: 2026-10-22

| Ticker | Shares after 05-01 | Close 05-01 | Value | Weight | Adj close 05-01 | Adj close 05-02 | r | Weight x r |
|---|---|---|---|---|---|---|---|---|
| AAPL | 63 | 169.3000 | 10,665.90 | 0.089621 | 167.4743 | 171.1640 | 0.022032 | 0.001975 |
| CVX | 55 | 159.6300 | 8,779.65 | 0.073771 | 143.8364 | 144.8275 | 0.006891 | 0.000508 |
| JNJ | 54 | 151.1800 | 8,163.72 | 0.068596 | 140.9998 | 139.8247 | -0.008334 | -0.000572 |
| JPM | 71 | 191.8600 | 13,622.06 | 0.114460 | 182.2002 | 182.0103 | -0.001042 | -0.000119 |
| KO | 125 | 61.9300 | 7,741.25 | 0.065046 | 57.7182 | 57.7742 | 0.000969 | 0.000063 |
| MSFT | 45 | 394.9400 | 17,772.30 | 0.149332 | 387.3999 | 390.2445 | 0.007343 | 0.001097 |
| PG | 53 | 163.4000 | 8,660.20 | 0.072768 | 153.8921 | 154.3064 | 0.002693 | 0.000196 |
| UNH | 11 | 484.1100 | 5,325.21 | 0.044745 | 457.9704 | 466.3520 | 0.018302 | 0.000819 |
| XLF | 400 | 40.3600 | 16,144.00 | 0.135651 | 38.8626 | 38.9589 | 0.002478 | 0.000336 |
| XLP | 74 | 75.0200 | 5,551.48 | 0.046647 | 70.1996 | 70.7891 | 0.008398 | 0.000392 |
| XLV | 47 | 140.5800 | 6,607.26 | 0.055518 | 134.8100 | 134.7142 | -0.000711 | -0.000039 |
| XOM | 86 | 116.0300 | 9,978.58 | 0.083845 | 107.0880 | 107.2818 | 0.001810 | 0.000152 |
| **Total** | | | 119,011.61 | **1.0000** | | | | **r_p (by hand)** = 0.004806339 |

r_p in fact_daily_portfolio: 0.00480633901305631  Difference: < 0.000000001 (agrees to 9 decimals; PASS)

Table values are rounded for display; the Excel sheet used full precision.

## Notes

- Weights use the unadjusted `close` (what the shares were worth); returns use
  `adj_close` (includes dividends). Same split as Stage 4.
- MSFT shows 45 and XLF 400 because the 2024-05-01 buys happened at that
  day's close, before the 05-02 return is earned.

---

# Hand check 3 (Stage 6): monthly rebalance on 2023-11-30

Purpose: prove, with a calculator or Excel and the raw prices file, that the
S2_MONTHLY backtest buys the right starting positions, values them correctly
a month later, rebalances back to the targets and charges the 10 bp cost
correctly (docs/backtest_rules.md sections 2 and 4).

## Method

1. **Starting value.** V0 = 100,000 / 1.001 (the base-day purchase pays
   0.10 of one percent of every dollar bought, out of the 100,000).
2. **Starting units.** From `data/raw/prices_daily.csv`, take `adj_close` (not
   `close`) on 2023-11-01. Units = target weight x V0 / adj_close.
3. **Value before rebalancing.** Take `adj_close` on 2023-11-30.
   Value = units x adj_close(11-30). V_pre = sum of the 12 values.
4. **Stored numbers.** In pgAdmin run:

       SELECT price_date, value
       FROM fact_backtest_daily
       WHERE strategy_code = 'S2_MONTHLY'
         AND price_date IN (DATE '2023-11-01', DATE '2023-11-30')
       ORDER BY price_date;

       SELECT ticker, side, units, price, traded_value, cost
       FROM fact_backtest_trades
       WHERE strategy_code = 'S2_MONTHLY' AND price_date = DATE '2023-11-30'
       ORDER BY ticker;

   V' = the stored value on 2023-11-30 (after the trades and the cost).
5. **Targets hit.** For each holding: target value = weight x V'.
   Traded value = |target value - value before|. BUY if the target is larger.
   Compare with `traded_value` and `side`.
6. **Cost.** Cost = 0.001 x sum of traded values. Then check
   V' + cost = V_pre (to the cent or better).

## Results

Filled in by hand on: ____________

V0 (by hand) = ____________   Stored value on 2023-11-01 = ____________

| Ticker | Weight | Adj close 11-01 | Units | Adj close 11-30 | Value before | Weight x V' | Traded value (by hand) | Side | Stored traded_value |
|---|---|---|---|---|---|---|---|---|---|
| AAPL | 0.11 | | | | | | | | |
| CVX | 0.08 | | | | | | | | |
| JNJ | 0.08 | | | | | | | | |
| JPM | 0.10 | | | | | | | | |
| KO | 0.07 | | | | | | | | |
| MSFT | 0.12 | | | | | | | | |
| PG | 0.08 | | | | | | | | |
| UNH | 0.06 | | | | | | | | |
| XLF | 0.10 | | | | | | | | |
| XLP | 0.05 | | | | | | | | |
| XLV | 0.06 | | | | | | | | |
| XOM | 0.09 | | | | | | | | |
| **Total** | **1.00** | | | | **V_pre =** | **V' =** | **sum =** | | |

Cost = 0.001 x sum = ____________   V' + cost = ____________   V_pre - (V' + cost) = ____________

## Notes

- Units are "adjusted units" (value / adj_close), not real shares, because the
  backtest trades at adjusted prices so dividends are reinvested automatically.
- Use the same CSV that the run used. yfinance restates old adj_close values
  when new dividends arrive, so a fresh download can differ slightly.
- You never have to solve the cost equation by hand: V' comes from the
  database, and steps 5 and 6 check that it is consistent.
