"""
src/check_analysis.py
---------------------
Stage 5 validation: PASS/FAIL checks on the analysis tables.

src/build_analysis.py calls run_checks() with
  * inputs: the Stage 4 model read from PostgreSQL (prices, view, rates, ...)
  * tables: the Stage 5 tables READ BACK from PostgreSQL after loading
so the checks test what Power BI will actually see, not just what Python
computed. Where possible a check recomputes a number a DIFFERENT way from
src/analysis.py (for example beta with numpy.polyfit instead of cov/var), so
a mistake in one method can't hide behind itself.

Checks are written in Python rather than SQL (the spec allowed either):
several need numpy (polyfit, standard deviations) and tolerances like 1e-12.

Each check returns (check_id, name, expected, actual, passed), the same five
fields as sql/06_validate_model.sql, and the output is printed the same way.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis import (
    BETA_WINDOW,
    CURRENT_RISK_WINDOW,
    TRADING_DAYS_PER_YEAR,
    VOL_WINDOWS,
    annual_to_daily,
    tbill_discount_to_bey,
)
from config import BENCHMARK_TICKER, PORTFOLIO_START


def _fmt(x) -> str:
    """Short text for a number in the output line."""
    if isinstance(x, (float, np.floating)):
        return f"{x:.3g}"
    return str(x)


def run_checks(inputs: dict[str, pd.DataFrame], tables: dict[str, pd.DataFrame]) -> list[tuple]:
    results: list[tuple] = []

    def check(cid: str, name: str, expected, actual, passed) -> None:
        results.append((cid, name, _fmt(expected), _fmt(actual), bool(passed)))

    spy = BENCHMARK_TICKER
    sec = inputs["securities"].set_index("ticker")
    holdings = sorted(sec.index[sec["role"] == "HOLDING"])
    n_hold = len(holdings)
    dates = pd.DatetimeIndex(inputs["dates"]["price_date"])
    return_days = dates[1:]
    n = len(return_days)

    daily = tables["fact_daily_portfolio"].set_index("price_date").sort_index()
    hr = tables["fact_daily_holding_returns"]
    corr = tables["fact_correlation"]
    epi = tables["fact_drawdown_episodes"]
    risk = tables["fact_risk_contribution"]
    hbeta = tables["fact_holding_beta"].set_index("ticker")
    summ = tables["analysis_summary"].set_index("metric_key")

    ret_rows = daily.loc[return_days]
    base = daily.loc[dates[0]]

    # Wide versions of the holding table: one column per ticker.
    w_prev = hr.pivot(index="price_date", columns="ticker", values="w_prev")
    c = hr.pivot(index="price_date", columns="ticker", values="contrib")
    lc = hr.pivot(index="price_date", columns="ticker", values="linked_contrib")

    # Prices from fact_prices, wide.
    pr = inputs["prices"]
    adj = pr.pivot(index="price_date", columns="ticker", values="adj_close_price").reindex(dates)
    close = pr.pivot(index="price_date", columns="ticker", values="close_price").reindex(dates)

    # ---------------- row counts ----------------
    check("A01", "fact_daily_portfolio rows = portfolio trading days",
          len(dates), len(daily), len(daily) == len(dates) and daily.index.equals(dates))
    check("A02", "fact_daily_holding_returns rows = holdings x return days",
          n_hold * n, len(hr), len(hr) == n_hold * n)

    # ---------------- base day ----------------
    base_ok = (dates[0] == pd.Timestamp(PORTFOLIO_START) and base["index_p"] == 100
               and base["index_spy"] == 100 and base["cum_p"] == 0 and base["dd_p"] == 0
               and pd.isna(base["r_p"]) and pd.isna(base["rf_daily"]) and bool(base["is_base_day"])
               and daily["is_base_day"].sum() == 1)
    check("A03", "Base day 2023-11-01: index 100, no return, no rf, one base row",
          "true", base_ok, base_ok)

    # ---------------- weights and contributions ----------------
    err = (w_prev.sum(axis=1) - 1).abs().max()
    check("A04", "Weights at previous close sum to 1 on every return day (1e-12)",
          "< 1e-12", err, err < 1e-12)

    err = (c.sum(axis=1) - ret_rows["r_p"]).abs().max()
    check("A05", "Sum of contributions = r_p on every return day (1e-12)",
          "< 1e-12", err, err < 1e-12)

    # Recompute G from the stored r_p, independently of growth_prev / index_p.
    g = (1 + ret_rows["r_p"]).cumprod()
    err = (100 * g - ret_rows["index_p"]).abs().max() / 100
    err2 = (g.shift(1).fillna(1.0) - ret_rows["growth_prev"]).abs().max()
    check("A06", "index_p = 100 x product(1 + r_p); growth_prev = G(t-1) (1e-9)",
          "< 1e-9", max(err, err2), max(err, err2) < 1e-9)

    total = ret_rows["cum_p"].iloc[-1]
    err = abs(lc.to_numpy().sum() - total)
    check("A07", "Sum of linked contributions = cumulative portfolio return (1e-9)",
          f"{total:.9f}", f"{lc.to_numpy().sum():.9f}", err < 1e-9)

    # Sub-period linking: for each calendar year, sum(linked)/G(s-1) = G(e)/G(s-1) - 1.
    worst = 0.0
    for _, idx in pd.Series(return_days, index=return_days).groupby(return_days.year):
        s, e = idx.iloc[0], idx.iloc[-1]
        g_before = daily.loc[s, "growth_prev"]
        g_end = 1 + daily.loc[e, "cum_p"]
        worst = max(worst, abs(lc.loc[s:e].to_numpy().sum() / g_before - (g_end / g_before - 1)))
    check("A08", "Linked contributions rescaled by growth_prev give each calendar year's return (1e-9)",
          "< 1e-9", worst, worst < 1e-9)

    # (c) price-only cross-check against the view.
    mv = daily["market_value"]
    lhs = (mv - daily["net_contribution"]) / mv.shift(1) - 1
    price_ret = (close[holdings] / close[holdings].shift(1) - 1).loc[return_days]
    rhs = (w_prev[holdings] * price_ret).sum(axis=1)
    err = (lhs.loc[return_days] - rhs).abs().max()
    check("A09", "Price-only check: (MV - net contribution) / previous MV - 1 = weighted price return (1e-9)",
          "< 1e-9", err, err < 1e-9)

    # Holding returns stored = adj close ratio from fact_prices.
    r_wide = hr.pivot(index="price_date", columns="ticker", values="r")
    r_check = (adj[holdings] / adj[holdings].shift(1) - 1).loc[return_days]
    err = (r_wide[holdings] - r_check).abs().max().max()
    check("A10", "Holding returns = adj_close(t) / adj_close(t-1) - 1 (1e-12)",
          "< 1e-12", err, err < 1e-12)

    # ---------------- SPY ----------------
    spy_cum = adj[spy].iloc[-1] / adj[spy].iloc[0] - 1
    err = abs(daily["cum_spy"].iloc[-1] - spy_cum)
    check("A11", "SPY cumulative = last adj close / base adj close - 1 (1e-9)",
          f"{spy_cum:.9f}", f"{daily['cum_spy'].iloc[-1]:.9f}", err < 1e-9)

    # ---------------- drawdowns ----------------
    ok = True
    details = []
    for col, series in (("dd_p", "PORTFOLIO"), ("dd_spy", "SPY")):
        e = epi[epi["series"] == series].sort_values("episode_no")
        mdd = daily[col].min()
        ok &= bool((daily[col] <= 0).all())
        ok &= abs(e.loc[e["depth_rank"] == 1, "depth"].iloc[0] - mdd) < 1e-12
        ok &= bool((e["recovered"] == e["recovery_date"].notna()).all())
        ok &= int((~e["recovered"]).sum()) <= 1 and (e["recovered"].iloc[:-1].all())
        details.append(f"{series} {mdd:.4f}")
    check("A12", "Drawdown <= 0; max drawdown = min(drawdown) = deepest episode; recovery flags consistent",
          "true", "; ".join(details), ok)

    # ---------------- rolling windows ----------------
    ok = True
    for w in VOL_WINDOWS:
        for col in (f"vol{w}_p", f"vol{w}_spy"):
            ok &= daily[col].isna().sum() == w
            ok &= daily[col].first_valid_index() == return_days[w - 1]
    ok &= daily["beta90_p"].isna().sum() == BETA_WINDOW
    ok &= daily["beta90_p"].first_valid_index() == return_days[BETA_WINDOW - 1]
    check("A13", "Rolling columns: NULL count = window (base day + window-1); first value on the window-th return day",
          "true", ok, ok)

    # Recompute the last 30-day volatility directly with numpy.
    last30 = ret_rows["r_p"].iloc[-30:].to_numpy()
    vol = np.std(last30, ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
    err = abs(vol - daily["vol30_p"].iloc[-1])
    check("A14", "Last vol30_p = numpy std of the last 30 returns x sqrt(252) (1e-12)",
          f"{vol:.6f}", f"{daily['vol30_p'].iloc[-1]:.6f}", err < 1e-12)

    # ---------------- beta ----------------
    # numpy.polyfit(x, y, 1) fits a straight line y = slope*x + intercept by
    # least squares; the slope is the beta.
    x_spy = (ret_rows["r_spy"] - ret_rows["rf_daily"]).to_numpy()
    x_p = (ret_rows["r_p"] - ret_rows["rf_daily"]).to_numpy()
    slope = np.polyfit(x_spy, x_p, 1)[0]
    err = abs(slope - summ.loc["beta", "portfolio_value"])
    for t in holdings:
        x_i = (r_wide[t] - ret_rows["rf_daily"]).to_numpy()
        err = max(err, abs(np.polyfit(x_spy, x_i, 1)[0] - hbeta.loc[t, "beta_excess"]))
    check("A15", "Beta (cov/var) = least-squares slope from numpy.polyfit, portfolio and 12 holdings (1e-9)",
          "< 1e-9", err, err < 1e-9)

    slope90 = np.polyfit(x_spy[-BETA_WINDOW:], x_p[-BETA_WINDOW:], 1)[0]
    err = abs(slope90 - daily["beta90_p"].iloc[-1])
    check("A16", "Last rolling 90-day beta = polyfit slope over the last 90 return days (1e-9)",
          "< 1e-9", err, err < 1e-9)

    # ---------------- correlation ----------------
    m = corr.pivot(index="ticker_a", columns="ticker_b", values="correlation")
    diag_err = np.abs(np.diag(m.to_numpy()) - 1).max()
    sym_err = np.abs(m.to_numpy() - m.to_numpy().T).max()
    ok = len(corr) == (n_hold + 1) ** 2 and diag_err < 1e-12 and sym_err < 1e-12
    check("A17", "Correlation: 169 rows, diagonal = 1, symmetric (1e-12)",
          (n_hold + 1) ** 2, len(corr), ok)

    # ---------------- risk-free rate ----------------
    rf = ret_rows["rf_daily"]
    gap = (pd.Series(dates[:-1], index=return_days) - ret_rows["rf_rate_date"]).dt.days
    ok = (rf.notna().all() and rf.gt(0).all() and rf.lt(0.001).all()
          and gap.ge(0).all() and gap.le(7).all())
    check("A18", "rf_daily on every return day, between 0 and 0.001, from a DTB3 date 0-7 days before t-1",
          "true", f"max gap {gap.max()} days", ok)

    # Rebuild every rf value from fact_rates with the conversion functions.
    rates = inputs["rates"].set_index("rate_date")["dtb3_discount_pct"]
    raw = rates.reindex(ret_rows["rf_rate_date"]).to_numpy()
    expected_rf = annual_to_daily(tbill_discount_to_bey(pd.Series(raw)))
    err = np.abs(expected_rf.to_numpy() - rf.to_numpy()).max()
    check("A19", "rf_daily = conversion of the DTB3 value on rf_rate_date (1e-15)",
          "< 1e-15", err, err < 1e-15)

    # ---------------- risk contribution ----------------
    sums = risk.groupby("method")["risk_contribution"].sum()
    counts = risk.groupby("method")["ticker"].count()
    ok = (set(sums.index) == {"HISTORICAL", "CURRENT"} and (sums - 1).abs().max() < 1e-9
          and (counts == n_hold).all()
          and risk.loc[risk["method"] == "CURRENT", "return_days"].iloc[0] == min(CURRENT_RISK_WINDOW, n))
    check("A20", "Risk contributions sum to 1 for each method, 12 holdings each (1e-9)",
          "1, 1", ", ".join(f"{v:.12f}" for v in sums), ok)

    # ---------------- concentration ----------------
    vw = inputs["holdings"].pivot(index="price_date", columns="ticker", values="actual_weight").reindex(dates)
    hhi = (vw ** 2).sum(axis=1)
    err = max((hhi - daily["hhi"]).abs().max(),
              (1 / hhi - daily["effective_n"]).abs().max())
    ok = err < 1e-12 and daily["top5_share"].between(5 / n_hold, 1).all()
    check("A21", "HHI and effective N match the view's actual_weight (1e-12); top-5 share in range",
          "< 1e-12", err, ok)

    # ---------------- summary ----------------
    tot = summ.loc["total_return"]
    ann = (1 + tot["portfolio_value"]) ** (TRADING_DAYS_PER_YEAR / n) - 1
    vol_p = ret_rows["r_p"].std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
    rf_ann = summ.loc["avg_rf_annual", "portfolio_value"]
    sharpe = (ann - rf_ann) / vol_p
    errs = [
        abs(tot["portfolio_value"] - daily["cum_p"].iloc[-1]),
        abs(tot["spy_value"] - daily["cum_spy"].iloc[-1]),
        abs(summ.loc["annualized_return", "portfolio_value"] - ann),
        abs(summ.loc["annualized_volatility", "portfolio_value"] - vol_p),
        abs(summ.loc["sharpe_ratio", "portfolio_value"] - sharpe),
        abs(summ.loc["max_drawdown", "portfolio_value"] - daily["dd_p"].min()),
        abs(summ.loc["max_drawdown", "spy_value"] - daily["dd_spy"].min()),
        abs(summ.loc["return_days", "portfolio_value"] - n),
    ]
    check("A22", "Summary metrics agree with the daily table (1e-12)",
          "< 1e-12", max(errs), max(errs) < 1e-12)

    return results
