"""
src/analysis.py
---------------
Stage 5: computes every analysis metric defined in docs/methodology.md.

This module only CALCULATES. It does not write to the database and it does
not check results; those jobs live in two other files:
    src/analysis.py        load_inputs()  read the Stage 4 model from PostgreSQL
                           compute_all()  turn those inputs into the result tables
    src/check_analysis.py  PASS/FAIL validation of the results
    src/build_analysis.py  the script you run: compute, load, validate

Keeping the math in pure functions (DataFrames in, DataFrames out) means it can
be tested without a database, and the checks can recompute things
independently instead of trusting this file.

New pandas / numpy ideas used here (explained once):
* pivot(index=..., columns=..., values=...) reshapes a long table (one row per
  date per ticker) into a wide one (one row per date, one column per ticker).
  Wide tables let us do the same math on every ticker at once.
* shift(1) moves every value down one row, so on day t you see day t-1's
  value. That is how "previous trading day" is expressed.
* cumprod() is a running product (1st value, 1st x 2nd, 1st x 2nd x 3rd, ...),
  used to compound daily returns. cummax() is a running maximum.
* rolling(W) looks at the last W rows on every row, e.g. rolling(30).std() is
  a 30-day moving standard deviation. It returns NaN (empty) until W values
  are available.
* merge_asof is a "nearest earlier match" join: for each date it finds the
  latest row in the other table whose date is on or before it. That is
  exactly a forward-fill of the risk-free rate.
* A NaN (numpy "not a number") becomes NULL when written to PostgreSQL.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import text

from config import BENCHMARK_TICKER, PORTFOLIO_START

# ---------------------------------------------------------------------------
# Fixed parameters (methodology.md sections 1, 4, 5, 6, 10)
# ---------------------------------------------------------------------------
TRADING_DAYS_PER_YEAR = 252
VOL_WINDOWS = (30, 90)        # rolling volatility windows, in return days
BETA_WINDOW = 90              # rolling beta window, in return days
CURRENT_RISK_WINDOW = 252     # covariance window for the CURRENT risk contribution
TBILL_DAYS = 91               # term of a 13-week (3-month) bill, for the BEY formula


# ===========================================================================
# 1. Reading the Stage 4 model
# ===========================================================================
def load_inputs(engine) -> dict[str, pd.DataFrame]:
    """
    Read everything the analysis needs from PostgreSQL.
    Returns a dictionary of DataFrames with date columns as pandas Timestamps.
    """
    queries = {
        "securities": """
            SELECT ticker, sector, role, target_weight::double precision AS target_weight
            FROM dim_security
        """,
        # Trading days of the portfolio period, in order. This is the calendar
        # every result table follows.
        "dates": """
            SELECT date_key AS price_date
            FROM dim_date
            WHERE is_trading_day AND is_portfolio_period
            ORDER BY date_key
        """,
        "prices": """
            SELECT price_date, ticker, close_price, adj_close_price
            FROM fact_prices
            ORDER BY ticker, price_date
        """,
        "holdings": """
            SELECT price_date, ticker,
                   shares_held::double precision AS shares_held,
                   close_price, market_value, net_contribution, actual_weight
            FROM vw_daily_holdings
            ORDER BY price_date, ticker
        """,
        "rates": """
            SELECT rate_date, dtb3_discount_pct
            FROM fact_rates
            ORDER BY rate_date
        """,
    }
    out = {}
    with engine.connect() as conn:
        for name, sql in queries.items():
            out[name] = pd.read_sql(text(sql), conn)

    # PostgreSQL DATE columns arrive as Python dates; turn them into pandas
    # Timestamps so date math and joins behave the same everywhere.
    for name, col in [("dates", "price_date"), ("prices", "price_date"),
                      ("holdings", "price_date"), ("rates", "rate_date")]:
        out[name][col] = pd.to_datetime(out[name][col])
    return out


# ===========================================================================
# 2. Small building blocks
# ===========================================================================
def tbill_discount_to_bey(discount_pct: pd.Series, days: int = TBILL_DAYS) -> pd.Series:
    """
    T-bill discount rate (percent) -> bond-equivalent yield (fraction).
    BEY = 365 x d / (360 - d x days), the Treasury investment-rate formula for
    bills of 182 days or less (methodology.md section 4).
    """
    d = discount_pct / 100.0
    return 365.0 * d / (360.0 - d * days)


def annual_to_daily(annual: pd.Series) -> pd.Series:
    """Annual yield -> rate per trading day, compounded: (1 + y)^(1/252) - 1."""
    return (1.0 + annual) ** (1.0 / TRADING_DAYS_PER_YEAR) - 1.0


def drawdown_series(index: pd.Series) -> pd.Series:
    """drawdown(t) = index(t) / running max of index up to t - 1. Always <= 0."""
    return index / index.cummax() - 1.0


def drawdown_episodes(index: pd.Series, series_name: str) -> pd.DataFrame:
    """
    Split an index series into drawdown episodes (methodology.md section 8).

    Walks through the days in order. An episode starts on the first day the
    index is below its running maximum. Its peak is the day before (the last
    day at the maximum). It ends on the first day the index gets back to the
    peak level (recovery). The trough is the lowest day in between.
    "Trading days" are counted by position in the list of dates.
    """
    values = index.to_numpy()
    dates = index.index
    running_max = np.maximum.accumulate(values)

    rows = []
    k = 1
    n = len(values)
    while k < n:
        if values[k] < running_max[k]:
            peak_pos = k - 1
            peak_val = values[peak_pos]
            trough_pos = k
            j = k
            recovery_pos = None
            while j < n:
                if values[j] >= peak_val:
                    recovery_pos = j
                    break
                if values[j] < values[trough_pos]:   # strict "<" keeps the FIRST lowest day on ties
                    trough_pos = j
                j += 1
            rows.append({
                "series": series_name,
                "peak_date": dates[peak_pos],
                "trough_date": dates[trough_pos],
                "recovery_date": dates[recovery_pos] if recovery_pos is not None else pd.NaT,
                "depth": values[trough_pos] / peak_val - 1.0,
                "days_to_trough": trough_pos - peak_pos,
                "days_to_recover": (recovery_pos - trough_pos) if recovery_pos is not None else None,
                "days_peak_to_recovery": (recovery_pos - peak_pos) if recovery_pos is not None else None,
                "recovered": recovery_pos is not None,
            })
            if recovery_pos is None:
                break
            k = recovery_pos + 1
        else:
            k += 1

    episodes = pd.DataFrame(rows, columns=[
        "series", "peak_date", "trough_date", "recovery_date", "depth", "days_to_trough",
        "days_to_recover", "days_peak_to_recovery", "recovered"])
    episodes.insert(1, "episode_no", np.arange(1, len(episodes) + 1))
    # rank(method="first"): deepest = 1; ties go to the earlier episode.
    episodes["depth_rank"] = episodes["depth"].rank(method="first").astype(int)
    # "Int64" (capital I) is pandas' whole-number type that allows blanks.
    for col in ("days_to_recover", "days_peak_to_recovery"):
        episodes[col] = episodes[col].astype("Int64")
    return episodes


def excess_beta(x: pd.Series, m: pd.Series) -> float:
    """Beta = sample covariance(x, m) / sample variance(m)."""
    return float(x.cov(m) / m.var())


# ===========================================================================
# 3. The full computation
# ===========================================================================
def compute_all(inputs: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Turn the Stage 4 inputs into the seven Stage 5 result tables."""
    sec = inputs["securities"].set_index("ticker")
    holdings_list = sorted(sec.index[sec["role"] == "HOLDING"])
    spy = BENCHMARK_TICKER
    all_tickers = holdings_list + [spy]

    dates = pd.DatetimeIndex(inputs["dates"]["price_date"])
    if dates[0] != pd.Timestamp(PORTFOLIO_START):
        raise ValueError(f"Portfolio period starts {dates[0].date()}, expected {PORTFOLIO_START}")
    base_day = dates[0]
    return_days = dates[1:]
    n_return_days = len(return_days)

    # ---- wide price tables: one row per date, one column per ticker ----------
    prices = inputs["prices"]
    adj = prices.pivot(index="price_date", columns="ticker", values="adj_close_price")
    adj = adj.reindex(index=dates, columns=all_tickers)

    # (a) daily returns from adjusted closes over consecutive trading days.
    # Written out instead of pct_change() so the formula is visible.
    rets = adj / adj.shift(1) - 1.0             # base-day row is NaN (no previous day in the period)

    # ---- market values and weights from the view ----------------------------
    h = inputs["holdings"]
    mv = h.pivot(index="price_date", columns="ticker", values="market_value")
    mv = mv.reindex(index=dates, columns=holdings_list).fillna(0.0)   # 0 = not held that day
    nc_total = (h.groupby("price_date")["net_contribution"].sum()
                 .reindex(dates).fillna(0.0))
    mv_total = mv.sum(axis=1)

    w_eod = mv.div(mv_total, axis=0)            # end-of-day weights, after that day's trades
    w_prev = w_eod.shift(1)                     # (b) start-of-day weights = previous close

    # ---- (b) time-weighted portfolio return ---------------------------------
    contrib = (w_prev * rets[holdings_list]).loc[return_days]       # (i) c(i,t)
    r_p = contrib.sum(axis=1)                                        # r_p(t) = sum of c(i,t)
    r_spy = rets.loc[return_days, spy]

    def growth(r: pd.Series) -> pd.Series:
        """G(t): growth of 1 from the base day, base day = 1."""
        g = (1.0 + r).cumprod()
        return pd.concat([pd.Series([1.0], index=[base_day]), g])

    g_p = growth(r_p)
    g_spy = growth(r_spy)
    growth_prev = g_p.shift(1).loc[return_days]                       # G(t-1)

    # ---- (i) linked contributions -------------------------------------------
    linked = contrib.mul(growth_prev, axis=0)

    # ---- (d) risk-free rate ---------------------------------------------------
    rates = inputs["rates"].dropna(subset=["dtb3_discount_pct"]).copy()
    rates["rf_annual"] = tbill_discount_to_bey(rates["dtb3_discount_pct"])
    rates["rf_daily"] = annual_to_daily(rates["rf_annual"])
    # For each return day t, use the latest DTB3 value on or before t-1.
    rf_lookup = pd.DataFrame({"price_date": return_days, "prev_day": dates[:-1]})
    rf_lookup = pd.merge_asof(
        rf_lookup.sort_values("prev_day"),
        rates[["rate_date", "rf_annual", "rf_daily"]].sort_values("rate_date"),
        left_on="prev_day", right_on="rate_date", direction="backward",
    ).set_index("price_date")
    rf_daily = rf_lookup["rf_daily"]

    # ---- (e) rolling volatility (raw returns, return days only) --------------
    sqrt_year = np.sqrt(TRADING_DAYS_PER_YEAR)
    vols = {}
    for w in VOL_WINDOWS:
        vols[f"vol{w}_p"] = r_p.rolling(w).std(ddof=1) * sqrt_year
        vols[f"vol{w}_spy"] = r_spy.rolling(w).std(ddof=1) * sqrt_year

    # ---- (f) beta on excess returns ------------------------------------------
    x_p = r_p - rf_daily
    x_spy = r_spy - rf_daily
    beta90 = x_p.rolling(BETA_WINDOW).cov(x_spy) / x_spy.rolling(BETA_WINDOW).var()
    beta_p = excess_beta(x_p, x_spy)
    beta_p_raw = excess_beta(r_p, r_spy)

    holding_beta = pd.DataFrame({
        "ticker": holdings_list,
        "beta_excess": [excess_beta(rets.loc[return_days, t] - rf_daily, x_spy) for t in holdings_list],
        "beta_raw": [excess_beta(rets.loc[return_days, t], r_spy) for t in holdings_list],
    })

    # ---- (g) correlation matrix, long format ---------------------------------
    corr = rets.loc[return_days, all_tickers].corr(method="pearson")
    # Display order: sectors alphabetically, tickers alphabetically within, SPY last.
    # sorted(..., key=...) sorts by the tuple the key returns: first by
    # "is it SPY" (False before True), then sector, then ticker.
    order = sorted(all_tickers, key=lambda t: (t == spy, sec.loc[t, "sector"], t))
    sort_pos = {t: i + 1 for i, t in enumerate(order)}
    # stack() turns the wide matrix back into long rows (one per pair).
    # melt() turns a wide table back into long rows: one row per (row label,
    # column) pair. Here: one row per (ticker_a, ticker_b) pair.
    corr_long = (corr.rename_axis(index="ticker_a", columns=None).reset_index()
                 .melt(id_vars="ticker_a", var_name="ticker_b", value_name="correlation"))
    corr_long["sort_a"] = corr_long["ticker_a"].map(sort_pos)
    corr_long["sort_b"] = corr_long["ticker_b"].map(sort_pos)

    # ---- (h) drawdowns ---------------------------------------------------------
    index_p = 100.0 * g_p
    index_spy = 100.0 * g_spy
    dd_p = drawdown_series(index_p)
    dd_spy = drawdown_series(index_spy)
    episodes = pd.concat([drawdown_episodes(index_p, "PORTFOLIO"),
                          drawdown_episodes(index_spy, "SPY")], ignore_index=True)

    # ---- (j) risk contribution --------------------------------------------------
    var_p = r_p.var()
    rc_hist = contrib.apply(lambda col: col.cov(r_p)) / var_p
    risk_hist = pd.DataFrame({
        "method": "HISTORICAL",
        "ticker": holdings_list,
        "weight_used": w_prev.loc[return_days, holdings_list].mean().to_numpy(),
        "risk_contribution": rc_hist.loc[holdings_list].to_numpy(),
        "window_start": return_days[0],
        "window_end": return_days[-1],
        "return_days": n_return_days,
    })

    cur_days = return_days[-min(CURRENT_RISK_WINDOW, n_return_days):]
    sigma = rets.loc[cur_days, holdings_list].cov()          # 12 x 12 covariance matrix
    w_last = w_eod.loc[dates[-1], holdings_list]
    sigma_w = sigma.to_numpy() @ w_last.to_numpy()            # "@" = matrix multiplication
    port_var = float(w_last.to_numpy() @ sigma_w)
    risk_cur = pd.DataFrame({
        "method": "CURRENT",
        "ticker": holdings_list,
        "weight_used": w_last.to_numpy(),
        "risk_contribution": w_last.to_numpy() * sigma_w / port_var,
        "window_start": cur_days[0],
        "window_end": cur_days[-1],
        "return_days": len(cur_days),
    })
    risk = pd.concat([risk_hist, risk_cur], ignore_index=True)

    # ---- (k) concentration (end-of-day weights, every day incl. base) --------
    target = sec.loc[holdings_list, "target_weight"]
    hhi = (w_eod ** 2).sum(axis=1)
    # For each day: sort the 12 weights, add up the 5 largest.
    top5 = w_eod.apply(lambda row: row.nlargest(5).sum(), axis=1)
    abs_drift = (w_eod - target).abs()

    # ---- fact_daily_portfolio ----------------------------------------------------
    daily = pd.DataFrame(index=dates)
    daily.index.name = "price_date"
    daily["is_base_day"] = daily.index == base_day
    daily["market_value"] = mv_total
    daily["net_contribution"] = nc_total
    daily["r_p"] = r_p                          # NaN on the base day (index alignment)
    daily["r_spy"] = r_spy
    daily["rf_rate_date"] = rf_lookup["rate_date"]
    daily["rf_annual"] = rf_lookup["rf_annual"]
    daily["rf_daily"] = rf_daily
    daily["growth_prev"] = growth_prev
    daily["index_p"] = index_p
    daily["index_spy"] = index_spy
    daily["cum_p"] = g_p - 1.0
    daily["cum_spy"] = g_spy - 1.0
    daily["dd_p"] = dd_p
    daily["dd_spy"] = dd_spy
    for col in ("vol30_p", "vol90_p", "vol30_spy", "vol90_spy"):
        daily[col] = vols[col]
    daily["beta90_p"] = beta90
    daily["hhi"] = hhi
    daily["effective_n"] = 1.0 / hhi
    daily["top5_share"] = top5
    daily["max_abs_drift"] = abs_drift.max(axis=1)
    daily["max_drift_ticker"] = abs_drift.idxmax(axis=1)
    daily = daily.reset_index()

    # ---- fact_daily_holding_returns (long format) -------------------------------
    def long(df: pd.DataFrame, name: str) -> pd.DataFrame:
        """Wide (date x ticker) -> long rows: price_date, ticker, <name>."""
        return (df.rename_axis(index="price_date", columns=None).reset_index()
                  .melt(id_vars="price_date", var_name="ticker", value_name=name))

    keys = ["price_date", "ticker"]
    hold_ret = (long(rets.loc[return_days, holdings_list], "r")
                .merge(long(w_prev.loc[return_days, holdings_list], "w_prev"), on=keys)
                .merge(long(contrib, "contrib"), on=keys)
                .merge(long(linked, "linked_contrib"), on=keys)
                .sort_values(keys).reset_index(drop=True))

    # ---- (l) summary ----------------------------------------------------------------
    summary = build_summary(
        r_p=r_p, r_spy=r_spy, rf_daily=rf_daily, g_p=g_p, g_spy=g_spy,
        dd_p=dd_p, dd_spy=dd_spy, beta_p=beta_p, beta_p_raw=beta_p_raw,
        mv_end=float(mv_total.iloc[-1]), nc_sum=float(nc_total.sum()),
        start=base_day, end=dates[-1],
    )

    return {
        "fact_daily_portfolio": daily,
        "fact_daily_holding_returns": hold_ret,
        "fact_correlation": corr_long,
        "fact_drawdown_episodes": episodes,
        "fact_risk_contribution": risk,
        "fact_holding_beta": holding_beta,
        "analysis_summary": summary,
    }


def build_summary(*, r_p, r_spy, rf_daily, g_p, g_spy, dd_p, dd_spy,
                  beta_p, beta_p_raw, mv_end, nc_sum, start, end) -> pd.DataFrame:
    """Full-period reference metrics (methodology.md section 12)."""
    n = len(r_p)
    yr = TRADING_DAYS_PER_YEAR

    def ann_return(total: float) -> float:
        return (1.0 + total) ** (yr / n) - 1.0

    tot_p, tot_spy = g_p.iloc[-1] - 1.0, g_spy.iloc[-1] - 1.0
    ann_p, ann_spy = ann_return(tot_p), ann_return(tot_spy)
    vol_p = r_p.std(ddof=1) * np.sqrt(yr)
    vol_spy = r_spy.std(ddof=1) * np.sqrt(yr)
    rf_ann = (1.0 + rf_daily.mean()) ** yr - 1.0

    # (key, name, portfolio, spy, unit, definition)
    rows = [
        ("total_return", "Total return", tot_p, tot_spy, "fraction",
         "Compounded time-weighted return from the base day to the last day"),
        ("annualized_return", "Annualized return", ann_p, ann_spy, "fraction",
         "(1 + total return) ^ (252 / N) - 1, N = return days"),
        ("annualized_volatility", "Annualized volatility", vol_p, vol_spy, "fraction",
         "Sample standard deviation of daily returns x sqrt(252)"),
        ("avg_rf_annual", "Average risk-free rate (annual)", rf_ann, rf_ann, "fraction",
         "(1 + mean daily risk-free rate) ^ 252 - 1, from DTB3 converted to bond-equivalent yield"),
        ("sharpe_ratio", "Sharpe ratio", (ann_p - rf_ann) / vol_p, (ann_spy - rf_ann) / vol_spy, "ratio",
         "(Annualized return - average risk-free rate) / annualized volatility"),
        ("max_drawdown", "Max drawdown", dd_p.min(), dd_spy.min(), "fraction",
         "Lowest value of index / running max of index - 1"),
        ("beta", "Beta vs SPY", beta_p, 1.0, "ratio",
         "cov(excess portfolio, excess SPY) / var(excess SPY), daily, full period"),
        ("beta_raw", "Beta vs SPY (raw returns, comparison only)", beta_p_raw, 1.0, "ratio",
         "Same as beta but without subtracting the risk-free rate"),
        ("excess_return_annualized", "Excess return vs SPY (annualized)", ann_p - ann_spy, np.nan, "fraction",
         "Portfolio annualized return - SPY annualized return"),
        ("excess_return_total", "Excess return vs SPY (total)", tot_p - tot_spy, np.nan, "fraction",
         "Portfolio total return - SPY total return"),
        ("ending_market_value", "Ending market value", mv_end, np.nan, "USD",
         "Shares held x close on the last day (no dividends, no cash)"),
        ("net_contributions", "Net contributions", nc_sum, np.nan, "USD",
         "Buys minus sale proceeds over the whole period"),
        ("return_days", "Return days (N)", float(n), float(n), "days",
         "Trading days after the base day"),
    ]
    out = pd.DataFrame(rows, columns=["metric_key", "metric_name", "portfolio_value",
                                      "spy_value", "unit", "definition"])
    out["period_start"] = start
    out["period_end"] = end
    out["sort_order"] = np.arange(1, len(out) + 1)
    return out
