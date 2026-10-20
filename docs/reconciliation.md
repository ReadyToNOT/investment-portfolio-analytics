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

Filled in by hand on: ____________

| Date | Trades counted | Shares held | Close (from CSV) | Shares × close (by hand) | Value in view | Difference |
|---|---|---|---|---|---|---|
| 2023-11-01 (first buy) | T002 | | | | | |
| 2025-07-31 (day before sale) | T002 | | | | | |
| 2025-08-01 (sale day) | T002, T019 | | | | | |
| last price date: ________ | T002, T019 | | | | | |

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

Filled in by hand on: ____________

| Ticker | Shares after 05-01 | Close 05-01 | Value | Weight | Adj close 05-01 | Adj close 05-02 | r | Weight x r |
|---|---|---|---|---|---|---|---|---|
| AAPL | 63 | | | | | | | |
| CVX | 55 | | | | | | | |
| JNJ | 54 | | | | | | | |
| JPM | 71 | | | | | | | |
| KO | 125 | | | | | | | |
| MSFT | 45 | | | | | | | |
| PG | 53 | | | | | | | |
| UNH | 11 | | | | | | | |
| XLF | 400 | | | | | | | |
| XLP | 74 | | | | | | | |
| XLV | 47 | | | | | | | |
| XOM | 86 | | | | | | | |
| **Total** | | | | **1.0000** | | | | **r_p (by hand)** = |

r_p in fact_daily_portfolio: ____________  Difference: ____________

## Notes

- Weights use the unadjusted `close` (what the shares were worth); returns use
  `adj_close` (includes dividends). Same split as Stage 4.
- MSFT shows 45 and XLF 400 because the 2024-05-01 buys happened at that
  day's close, before the 05-02 return is earned.
