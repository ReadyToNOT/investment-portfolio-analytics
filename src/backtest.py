"""
src/backtest.py
---------------
Stage 6: the strategy backtest defined in docs/backtest_rules.md.

This module only CALCULATES (DataFrames in, DataFrames out). It does not write
to the database and it does not check results:
    src/backtest.py        load_inputs()  read the Stage 4/5 tables
                           compute_all()  simulate every strategy, build the tables
    src/check_backtest.py  PASS/FAIL checks B01-B22
    src/build_backtest.py  the script you run: compute, load, read back, check

Every rule, parameter and cost below was fixed in docs/backtest_rules.md
BEFORE any result existed. Do not change a value here without logging the
change and the reason in section 10 of that file.

New ideas used here (explained once):
* A "simulation" walks forward one trading day at a time and keeps track of
  what the strategy owns (units of each holding and cash), the way an
  account statement would.
* "Adjusted units": we trade at adj_close, which already includes dividends.
  So one unit is "one share's worth at adjusted prices", not a real share.
  Value = units x adj_close, so dividends grow the value automatically.
* numpy arrays (np.array) are fast lists of numbers. a @ b multiplies two
  arrays element by element and adds the results up (a "dot product"), e.g.
  units @ prices = total value of all positions.
* A "fixed-point iteration" solves an equation of the form x = f(x) by
  starting with a guess, computing f(guess), feeding the answer back in, and
  repeating until the number stops changing. We use it because the trading
  cost depends on the size of the trades, and the size of the trades depends
  on the value left after paying the cost.
* A dict (dictionary) maps keys to values, e.g. {date: weights}. "d in sched"
  asks whether that date is one of the keys.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text

from analysis import TRADING_DAYS_PER_YEAR, drawdown_episodes, drawdown_series, excess_beta
from config import HOLIDAY_YEARS_COVERED, NYSE_HOLIDAYS, PORTFOLIO_START, WARMUP_TRADING_DAYS_NEEDED

# ---------------------------------------------------------------------------
# Fixed parameters (docs/backtest_rules.md, sections 2 to 4)
# ---------------------------------------------------------------------------
START_CAPITAL = 100_000.0           # dollars in cash just before the base-day close
COST_LEVELS_BPS = (0, 10, 25)       # basis points: 1 bp = 0.0001 of traded value
HEADLINE_BPS = 10                   # the one cost level used for the headline
SMA_SHORT = 50                      # short moving-average window, trading days
SMA_LONG = 200                      # long moving-average window, trading days
FIXED_POINT_TOL = 1e-10             # dollars: stop iterating when V' changes less than this
FIXED_POINT_MAX_ITER = 100
MIN_TRADE_VALUE = 1e-9              # dollars: smaller "trades" are rounding noise, no row written

if SMA_LONG > WARMUP_TRADING_DAYS_NEEDED:
    raise ValueError("SMA_LONG is longer than the warm-up history config.py downloads")

# Strategy codes (the primary key of dim_strategy).
S1, S2, S3 = "S1_BUY_HOLD", "S2_MONTHLY", "S3_MA_50_200"
ACTUAL, SPY_REF = "ACTUAL", "SPY"
STRATEGIES = (S1, S2, S3)

DIM_STRATEGY = pd.DataFrame(
    [
        (S1, "Buy and hold", 1, False,
         "Buy the 12 holdings at target weights on 2023-11-01 and never trade again."),
        (S2, "Monthly rebalance", 2, False,
         "Trade every holding back to its target weight at the close of each month-end trading day."),
        (S3, "50/200-day MA filter", 3, False,
         "Monthly: hold a holding at its target weight if its 50-day average is above its "
         "200-day average on the previous day, otherwise keep that slice in cash."),
        (ACTUAL, "Actual portfolio (reference)", 4, True,
         "Time-weighted return of the sample portfolio from Stage 5, with its real top-ups and sale."),
        (SPY_REF, "SPY benchmark (reference)", 5, True,
         "SPY total return from Stage 5. Never traded."),
    ],
    columns=["strategy_code", "strategy_name", "sort_order", "is_reference", "description"],
)

# Summary metrics: (key, display name, unit, definition). The list order is the sort order.
METRIC_DEFS = [
    ("total_return", "Total return", "fraction",
     "Index on the last day / 100 - 1"),
    ("annualized_return", "Annualized return", "fraction",
     "(1 + total return) ^ (252 / N) - 1, N = return days"),
    ("annualized_volatility", "Annualized volatility", "fraction",
     "Sample standard deviation of daily returns x sqrt(252)"),
    ("avg_rf_annual", "Average risk-free rate (annual)", "fraction",
     "(1 + mean daily risk-free rate) ^ 252 - 1, same as analysis_summary"),
    ("sharpe_ratio", "Sharpe ratio", "ratio",
     "(Annualized return - average risk-free rate) / annualized volatility"),
    ("max_drawdown", "Max drawdown", "fraction",
     "Lowest value of index / running max of index - 1"),
    ("beta", "Beta vs SPY", "ratio",
     "cov(excess return, excess SPY return) / var(excess SPY return), daily, full period"),
    ("beta_raw", "Beta vs SPY (raw returns, comparison only)", "ratio",
     "Same as beta but without subtracting the risk-free rate"),
    ("excess_return_annualized", "Excess return vs SPY (annualized)", "fraction",
     "Annualized return - SPY annualized return"),
    ("ending_value", "Ending value", "USD",
     "Value on the last day after costs; started at 100,000 minus the initial purchase cost"),
    ("trades_total", "Number of trades", "count",
     "Trade rows, initial purchase included"),
    ("trades_after_start", "Number of trades after the start", "count",
     "Trade rows, initial purchase excluded"),
    ("turnover_annualized", "Turnover (annualized, buys + sells)", "fraction",
     "Traded value after the base day / average daily value x (252 / N)"),
    ("total_costs", "Total trading costs", "USD",
     "Sum of the cost of every trade, initial purchase included"),
    ("avg_cash_weight", "Average cash weight", "fraction",
     "Mean of cash / value over all days, base day included"),
    ("return_days", "Return days (N)", "days",
     "Trading days after the base day"),
]
METRIC_INFO = {k: (name, unit, definition, i + 1) for i, (k, name, unit, definition) in enumerate(METRIC_DEFS)}


# ===========================================================================
# 1. Reading the inputs
# ===========================================================================
def load_inputs(engine) -> dict[str, pd.DataFrame]:
    """Read everything the backtest needs from PostgreSQL (Stage 4 and Stage 5 tables)."""
    queries = {
        "securities": """
            SELECT ticker, role, target_weight::double precision AS target_weight
            FROM dim_security
        """,
        # ALL trading days, including the warm-up history before 2023-11-01,
        # because the 200-day average needs it.
        "calendar": """
            SELECT date_key AS price_date, is_month_end_trading_day, is_portfolio_period
            FROM dim_date
            WHERE is_trading_day
            ORDER BY date_key
        """,
        "prices": """
            SELECT price_date, ticker, adj_close_price
            FROM fact_prices
        """,
        # Stage 5 output: the portfolio period, the risk-free rate and the two references.
        "portfolio": """
            SELECT price_date, market_value, r_p, r_spy, rf_daily,
                   index_p, index_spy, dd_p, dd_spy
            FROM fact_daily_portfolio
            ORDER BY price_date
        """,
        "analysis_summary": """
            SELECT metric_key, portfolio_value, spy_value
            FROM analysis_summary
        """,
    }
    out = {}
    with engine.connect() as conn:
        for name, sql in queries.items():
            out[name] = pd.read_sql(text(sql), conn)
    for name in ("calendar", "prices", "portfolio"):
        out[name]["price_date"] = pd.to_datetime(out[name]["price_date"])
    return out


# ===========================================================================
# 2. Calendar: which days the strategies trade
# ===========================================================================
def true_last_trading_day_of_month(d: date) -> date:
    """
    The last NYSE trading day of d's calendar month, from the calendar itself
    (weekdays minus config.NYSE_HOLIDAYS), not from the price data.
    """
    if d.year not in HOLIDAY_YEARS_COVERED:
        raise ValueError(f"{d.year} is not in config.HOLIDAY_YEARS_COVERED; can't test month-ends")
    last = date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
    # weekday(): Monday = 0 ... Sunday = 6, so >= 5 means weekend.
    while last.weekday() >= 5 or last in NYSE_HOLIDAYS:
        last -= timedelta(days=1)
    return last


def month_end_trade_dates(cal: pd.DataFrame, base_day: pd.Timestamp,
                          last_day: pd.Timestamp) -> pd.DatetimeIndex:
    """
    Rebalance dates (backtest_rules.md section 2): days flagged
    is_month_end_trading_day, strictly after the base day, up to the last day.
    dim_date flags the last price date of an UNFINISHED month too, so that day
    is dropped unless it really is the last trading day of its month.
    """
    in_window = (cal["price_date"] > base_day) & (cal["price_date"] <= last_day)
    flagged = cal.loc[cal["is_month_end_trading_day"] & in_window, "price_date"]
    keep = [d for d in flagged
            if d != last_day or true_last_trading_day_of_month(d.date()) == d.date()]
    return pd.DatetimeIndex(keep)


# ===========================================================================
# 3. The 50/200-day moving-average signal
# ===========================================================================
def ma_signal(adj_full: pd.DataFrame, signal_date: pd.Timestamp) -> pd.Series:
    """
    ON (True) / OFF (False) per holding at the close of signal_date.

    Look-ahead protection by construction: the price table is CUT at
    signal_date first (.loc[:signal_date] keeps rows up to and including it),
    so no later price can reach the averages.
    ON when the 50-day simple average is strictly above the 200-day one; a tie is OFF.
    """
    hist = adj_full.loc[:signal_date]
    if len(hist) < SMA_LONG:
        raise ValueError(f"Only {len(hist)} trading days up to {signal_date.date()}, need {SMA_LONG}")
    window = hist.iloc[-SMA_LONG:]                  # the last 200 rows
    if window.isna().any().any():
        raise ValueError(f"Missing adj_close in the 200 days up to {signal_date.date()}")
    sma_short = window.iloc[-SMA_SHORT:].mean()     # mean of each column = one average per ticker
    sma_long = window.mean()
    return sma_short > sma_long


def ma_decisions(adj_full: pd.DataFrame, exec_dates: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.Series]:
    """
    For each execution date t, the signal from the PREVIOUS trading day (t-1).
    Returns (decisions: exec_date x ticker True/False, signal_date per exec_date).
    """
    pos = adj_full.index.get_indexer(exec_dates)     # row number of each date; -1 = not found
    if (pos < 1).any():
        raise ValueError("An execution date is missing from the price calendar or has no previous day")
    signal_dates = adj_full.index[pos - 1]
    rows = [ma_signal(adj_full, s) for s in signal_dates]
    decisions = pd.DataFrame(rows, index=exec_dates)
    decisions.index.name = "exec_date"
    return decisions, pd.Series(signal_dates, index=exec_dates, name="signal_date")


# ===========================================================================
# 4. Trading and simulation
# ===========================================================================
def rebalance(v_pre: float, units: np.ndarray, prices: np.ndarray,
              weights: np.ndarray, cost_rate: float) -> tuple[float, np.ndarray, int]:
    """
    Trade to `weights` and pay costs out of the portfolio (backtest_rules.md section 4).

    Solves V' = V_pre - c x sum |w_i x V' - units_i x P_i| by fixed-point
    iteration. Returns (V', new units, iterations used). Cash is set by the
    caller as w_cash x V'.
    """
    held = units * prices                           # current dollar value of each position
    v = v_pre
    for iteration in range(1, FIXED_POINT_MAX_ITER + 1):
        v_new = v_pre - cost_rate * np.abs(weights * v - held).sum()
        if abs(v_new - v) <= FIXED_POINT_TOL:
            v = v_new
            break
        v = v_new
    else:   # a for-loop's "else" runs only if the loop never hit "break"
        raise RuntimeError(f"Cost fixed point did not converge in {FIXED_POINT_MAX_ITER} iterations")
    return v, weights * v / prices, iteration


def simulate(adj: pd.DataFrame, rf_daily: pd.Series,
             schedule: dict[pd.Timestamp, tuple[np.ndarray, float]],
             cost_rate: float) -> dict[str, pd.DataFrame]:
    """
    Walk through the portfolio period one day at a time (rules section 2,
    "order of operations").

    adj       adjusted closes, portfolio-period dates x the 12 holdings
    rf_daily  daily risk-free rate per date (NaN on the base day, not used there)
    schedule  {trade date: (target weight per holding, cash weight)}; must include the base day
    cost_rate 0.0010 for 10 bp

    Returns three DataFrames:
      daily   price_date, value_pre, value, cash, cost_paid, is_trade_date
      units   date x ticker, units held after that day's trades
      trades  price_date, ticker, side, units, price, traded_value, cost
    """
    dates = adj.index
    tickers = list(adj.columns)
    prices_all = adj.to_numpy(dtype=float)
    rf = rf_daily.reindex(dates).to_numpy(dtype=float)
    if np.isnan(prices_all).any():
        raise ValueError("Missing adj_close inside the portfolio period")
    if np.isnan(rf[1:]).any():
        raise ValueError("Missing rf_daily on a return day")
    if dates[0] not in schedule:
        raise ValueError("The schedule must start with the base day")

    n_days = len(dates)
    units = np.zeros(len(tickers))
    cash = START_CAPITAL            # before the base-day close everything is cash
    value_pre = np.empty(n_days)
    value = np.empty(n_days)
    cash_hist = np.empty(n_days)
    cost_hist = np.zeros(n_days)
    is_trade = np.zeros(n_days, dtype=bool)
    units_hist = np.empty((n_days, len(tickers)))
    trades = []

    for k, d in enumerate(dates):
        p = prices_all[k]
        # Step 1: cash earns one day of interest (not on the base day).
        if k > 0:
            cash = cash * (1.0 + rf[k])
        # Step 2: pre-trade value at today's close.
        v_pre = float(units @ p + cash)
        # Step 3: trade if today is a trade date.
        if d in schedule:
            weights, w_cash = schedule[d]
            v_target, new_units, _ = rebalance(v_pre, units, p, weights, cost_rate)
            delta = new_units - units
            traded = np.abs(delta) * p
            real = traded > MIN_TRADE_VALUE
            for i in np.nonzero(real)[0]:
                trades.append({
                    "price_date": d,
                    "ticker": tickers[i],
                    "side": "BUY" if delta[i] > 0 else "SELL",
                    "units": abs(float(delta[i])),
                    "price": float(p[i]),
                    "traded_value": float(traded[i]),
                    "cost": cost_rate * float(traded[i]),
                })
            cost_hist[k] = cost_rate * float(traded[real].sum())
            units = new_units
            cash = w_cash * v_target
            is_trade[k] = True
        # Step 4: post-trade value.
        value_pre[k] = v_pre
        value[k] = float(units @ p + cash)
        cash_hist[k] = cash
        units_hist[k] = units

    daily = pd.DataFrame({
        "price_date": dates,
        "value_pre": value_pre,
        "value": value,
        "cash": cash_hist,
        "cost_paid": cost_hist,
        "is_trade_date": is_trade,
    })
    units_df = pd.DataFrame(units_hist, index=dates, columns=tickers)
    trades_df = pd.DataFrame(trades, columns=["price_date", "ticker", "side", "units",
                                              "price", "traded_value", "cost"])
    return {"daily": daily, "units": units_df, "trades": trades_df}


# ===========================================================================
# 5. Metrics
# ===========================================================================
def performance_metrics(index: pd.Series, r: pd.Series, rf: pd.Series, r_spy: pd.Series) -> dict[str, float]:
    """
    Same formulas as analysis.build_summary (backtest_rules.md section 5).
    index: every day incl. the base day (100 there); r, rf, r_spy: return days only.
    """
    yr = TRADING_DAYS_PER_YEAR
    n = len(r)
    total = index.iloc[-1] / 100.0 - 1.0
    ann = (1.0 + total) ** (yr / n) - 1.0
    vol = r.std(ddof=1) * np.sqrt(yr)
    rf_ann = (1.0 + rf.mean()) ** yr - 1.0
    ann_spy = (1.0 + ((1.0 + r_spy).prod() - 1.0)) ** (yr / n) - 1.0
    return {
        "total_return": total,
        "annualized_return": ann,
        "annualized_volatility": vol,
        "avg_rf_annual": rf_ann,
        "sharpe_ratio": (ann - rf_ann) / vol,
        "max_drawdown": float(drawdown_series(index).min()),
        "beta": excess_beta(r - rf, r_spy - rf),
        "beta_raw": excess_beta(r, r_spy),
        "excess_return_annualized": ann - ann_spy,
        "return_days": float(n),
    }


def trading_metrics(sim: dict[str, pd.DataFrame]) -> dict[str, float]:
    """Trade counts, turnover, costs and cash (only exist for S1 to S3)."""
    d = sim["daily"]
    t = sim["trades"]
    base_day = d["price_date"].iloc[0]
    after = t[t["price_date"] > base_day]
    n = len(d) - 1
    return {
        "ending_value": float(d["value"].iloc[-1]),
        "trades_total": float(len(t)),
        "trades_after_start": float(len(after)),
        "turnover_annualized": float(after["traded_value"].sum() / d["value"].mean()
                                     * TRADING_DAYS_PER_YEAR / n),
        "total_costs": float(t["cost"].sum()),
        "avg_cash_weight": float((d["cash"] / d["value"]).mean()),
    }


def summary_rows(code: str, cost_bps: int, is_headline: bool, metrics: dict[str, float]) -> list[dict]:
    """Turn a {metric_key: value} dict into long rows for fact_backtest_summary."""
    rows = []
    for key, val in metrics.items():
        name, unit, definition, order = METRIC_INFO[key]
        rows.append({"strategy_code": code, "cost_bps": cost_bps, "is_headline": is_headline,
                     "metric_key": key, "metric_name": name, "value": float(val),
                     "unit": unit, "definition": definition, "sort_order": order})
    return rows


def strategy_daily_rows(code: str, sim: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """fact_backtest_daily rows for one simulated strategy."""
    d = sim["daily"].set_index("price_date")
    v = d["value"]
    index = 100.0 * v / v.iloc[0]
    return pd.DataFrame({
        "strategy_code": code,
        "price_date": d.index,
        "value": v.to_numpy(),
        "daily_return": (v / v.shift(1) - 1.0).to_numpy(),   # NaN (NULL) on the base day
        "index_value": index.to_numpy(),
        "cum_return": (index / 100.0 - 1.0).to_numpy(),
        "drawdown": drawdown_series(index).to_numpy(),
        "cash_weight": (d["cash"] / v).to_numpy(),
        "cost_paid": d["cost_paid"].to_numpy(),
    })


def reference_daily_rows(port: pd.DataFrame) -> pd.DataFrame:
    """fact_backtest_daily rows for ACTUAL and SPY, copied from fact_daily_portfolio."""
    actual = pd.DataFrame({
        "strategy_code": ACTUAL,
        "price_date": port.index,
        "value": port["market_value"].to_numpy(),
        "daily_return": port["r_p"].to_numpy(),
        "index_value": port["index_p"].to_numpy(),
        "cum_return": (port["index_p"] / 100.0 - 1.0).to_numpy(),
        "drawdown": port["dd_p"].to_numpy(),
        "cash_weight": np.nan,
        "cost_paid": np.nan,
    })
    spy = pd.DataFrame({
        "strategy_code": SPY_REF,
        "price_date": port.index,
        "value": np.nan,
        "daily_return": port["r_spy"].to_numpy(),
        "index_value": port["index_spy"].to_numpy(),
        "cum_return": (port["index_spy"] / 100.0 - 1.0).to_numpy(),
        "drawdown": port["dd_spy"].to_numpy(),
        "cash_weight": np.nan,
        "cost_paid": np.nan,
    })
    return pd.concat([actual, spy], ignore_index=True)


def worst_drawdown_row(code: str, index: pd.Series) -> dict:
    """The deepest drawdown episode (rank 1), using the Stage 5 episode function."""
    ep = drawdown_episodes(index, code)
    top = ep[ep["depth_rank"] == 1].iloc[0]
    return {
        "strategy_code": code,
        "peak_date": top["peak_date"],
        "trough_date": top["trough_date"],
        "recovery_date": top["recovery_date"],
        "depth": float(top["depth"]),
        "days_to_trough": int(top["days_to_trough"]),
        "days_peak_to_recovery": (None if pd.isna(top["days_peak_to_recovery"])
                                  else int(top["days_peak_to_recovery"])),
        "recovered": bool(top["recovered"]),
    }


# ===========================================================================
# 6. Everything together
# ===========================================================================
def compute_all(inputs: dict[str, pd.DataFrame]) -> dict:
    """
    Run S1 to S3 at 0, 10 and 25 bp and build the five output tables.

    Returns a dict with
      "tables": the five DataFrames to load into PostgreSQL
      plus the in-memory pieces the checks need (simulations, signals, dates).
    """
    # ---- holdings and target weights -----------------------------------------
    sec = inputs["securities"]
    hold = sec[sec["role"] == "HOLDING"].sort_values("ticker")
    targets_raw = pd.Series(hold["target_weight"].to_numpy(), index=hold["ticker"].to_numpy())
    if abs(targets_raw.sum() - 1.0) > 1e-12:
        raise ValueError(f"Target weights sum to {targets_raw.sum()}, expected 1")
    # Divide by the sum so the weights add to exactly 1 in floating point
    # (it moves each weight by at most about 1e-16).
    targets = targets_raw / targets_raw.sum()
    tickers = list(targets.index)

    # ---- dates ---------------------------------------------------------------
    cal = inputs["calendar"]
    port = inputs["portfolio"].set_index("price_date").sort_index()
    period = pd.DatetimeIndex(port.index)
    base_day, last_day = period[0], period[-1]
    if base_day != pd.Timestamp(PORTFOLIO_START):
        raise ValueError(f"fact_daily_portfolio starts {base_day.date()}, expected {PORTFOLIO_START}")
    cal_period = pd.DatetimeIndex(cal.loc[cal["is_portfolio_period"], "price_date"])
    if not cal_period.equals(period):
        raise ValueError("fact_daily_portfolio dates differ from dim_date's portfolio-period trading days")

    # ---- prices: full history (for the averages) and the portfolio period ----
    adj_full = (inputs["prices"]
                .pivot(index="price_date", columns="ticker", values="adj_close_price")
                .reindex(index=pd.DatetimeIndex(cal["price_date"]), columns=tickers))
    adj = adj_full.loc[period]

    rf_daily = port["rf_daily"]
    return_days = period[1:]
    rf_ret = rf_daily.loc[return_days]
    r_spy = port["r_spy"].loc[return_days]

    # ---- schedules -------------------------------------------------------------
    trade_dates = month_end_trade_dates(cal, base_day, last_day)
    exec_dates = pd.DatetimeIndex([base_day]).append(trade_dates)
    decisions, signal_dates = ma_decisions(adj_full, exec_dates)

    w = targets.to_numpy()
    schedules = {
        S1: {base_day: (w, 0.0)},
        S2: {d: (w, 0.0) for d in exec_dates},
        S3: {},
    }
    for d in exec_dates:
        on = decisions.loc[d, tickers].to_numpy(dtype=bool)
        # ON -> target weight; OFF -> 0 and its target weight goes to cash.
        schedules[S3][d] = (np.where(on, w, 0.0), float(w[~on].sum()))

    # ---- simulations: 3 strategies x 3 cost levels ----------------------------
    sims = {}
    for code in STRATEGIES:
        for bps in COST_LEVELS_BPS:
            sims[(code, bps)] = simulate(adj, rf_daily, schedules[code], bps / 10_000.0)

    # ---- fact_backtest_daily (headline cost + references) ---------------------
    daily = pd.concat(
        [strategy_daily_rows(code, sims[(code, HEADLINE_BPS)]) for code in STRATEGIES]
        + [reference_daily_rows(port)],
        ignore_index=True,
    )

    # ---- fact_backtest_trades (headline cost) ---------------------------------
    trades = pd.concat(
        [sims[(code, HEADLINE_BPS)]["trades"].assign(strategy_code=code) for code in STRATEGIES],
        ignore_index=True,
    )[["strategy_code", "price_date", "ticker", "side", "units", "price", "traded_value", "cost"]]

    # ---- fact_backtest_summary -------------------------------------------------
    rows = []
    for code in STRATEGIES:
        for bps in COST_LEVELS_BPS:
            sd = strategy_daily_rows(code, sims[(code, bps)]).set_index("price_date")
            m = performance_metrics(sd["index_value"], sd["daily_return"].loc[return_days], rf_ret, r_spy)
            m.update(trading_metrics(sims[(code, bps)]))
            rows += summary_rows(code, bps, bps == HEADLINE_BPS, m)
    rows += summary_rows(ACTUAL, 0, True,
                         performance_metrics(port["index_p"], port["r_p"].loc[return_days], rf_ret, r_spy))
    rows += summary_rows(SPY_REF, 0, True,
                         performance_metrics(port["index_spy"], r_spy, rf_ret, r_spy))
    summary = pd.DataFrame(rows)

    # ---- fact_backtest_worst_drawdown -----------------------------------------
    by_code = daily.set_index(["strategy_code", "price_date"])["index_value"]
    worst = pd.DataFrame([worst_drawdown_row(code, by_code.loc[code])
                          for code in DIM_STRATEGY["strategy_code"]])

    return {
        "tables": {
            "dim_strategy": DIM_STRATEGY.copy(),
            "fact_backtest_daily": daily,
            "fact_backtest_trades": trades,
            "fact_backtest_summary": summary,
            "fact_backtest_worst_drawdown": worst,
        },
        "sims": sims,
        "targets": targets,
        "adj_full": adj_full,
        "period": period,
        "trade_dates": trade_dates,
        "exec_dates": exec_dates,
        "decisions": decisions,
        "signal_dates": signal_dates,
    }
