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
