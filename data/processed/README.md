# data/processed — SAMPLE INPUTS

**Everything in this folder is a fictional sample portfolio built for an educational
analytics project. It is not anyone's real holdings and is not investment advice.**

| File | What it is |
|---|---|
| `security_lookup.csv` | One row per security: name, asset class, sector, role (HOLDING or BENCHMARK) and target weight. Source for `dim_security`. |
| `transactions.csv` | Fictional trade log in shares. Prices are NOT typed here; they come from the market data (closing price on the trade date). Source for `fact_transactions`. |

Conventions
- Trades are assumed to execute at the official closing price on `trade_date`, with no commissions.
- Every BUY is funded by new money contributed that day; every SELL's proceeds are withdrawn that day. The portfolio holds no cash.
- Shares are in today's (split-adjusted) terms. The holdings were chosen so that no split happened inside the data window.
- The risk-free rate (FRED series DTB3) lives in `fact_rates`, not here — it is not a security.
