"""
src/check_backtest.py
---------------------
Stage 6 validation: PASS/FAIL checks B01-B22 from docs/backtest_rules.md
section 7.

src/build_backtest.py calls run_checks() with
  * inputs:  the Stage 4/5 tables read from PostgreSQL (backtest.load_inputs)
  * result:  what backtest.compute_all returned (in-memory simulations at all
             three cost levels, signals, dates)
  * stored:  the five Stage 6 tables READ BACK from PostgreSQL
Most checks use the stored tables, so they test what Power BI will see. The
0 and 25 bp runs are not stored day by day, so checks on them use the
in-memory simulations. Where possible a check recomputes a number a
DIFFERENT way from src/backtest.py (for example the moving averages with
pandas rolling() instead of slicing, or positions rebuilt from the stored
trade rows), so a mistake can't hide behind itself.

Each check returns (check_id, name, expected, actual, passed), the same
five fields as check_analysis.py.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from analysis import TRADING_DAYS_PER_YEAR
from backtest import (
    ACTUAL,
    COST_LEVELS_BPS,
    HEADLINE_BPS,
    S1,
    S2,
    S3,
    SMA_LONG,
    SMA_SHORT,
    SPY_REF,
    STRATEGIES,
    ma_decisions,
    true_last_trading_day_of_month,
)


def _fmt(x) -> str:
    """Short text for a number in the output line."""
    if isinstance(x, (float, np.floating)):
        return f"{x:.3g}"
    return str(x)


def _max_abs(a) -> float:
    """Largest absolute value in an array/Series/DataFrame (0 if empty)."""
    arr = np.abs(np.asarray(a, dtype=float))
    return float(arr.max()) if arr.size else 0.0


def run_checks(inputs: dict[str, pd.DataFrame], result: dict,
               stored: dict[str, pd.DataFrame]) -> list[tuple]:
    results: list[tuple] = []

    def check(cid: str, name: str, expected, actual, passed) -> None:
        results.append((cid, name, _fmt(expected), _fmt(actual), bool(passed)))

    sims = result["sims"]
    targets = result["targets"]
    tickers = list(targets.index)
    period = result["period"]
    base_day, last_day = period[0], period[-1]
    return_days = period[1:]
    n = len(return_days)
    yr = TRADING_DAYS_PER_YEAR

    port = inputs["portfolio"].set_index("price_date").sort_index()
    cal = inputs["calendar"]

    daily = stored["fact_backtest_daily"].sort_values(["strategy_code", "price_date"])
    trades = stored["fact_backtest_trades"]
    summ = stored["fact_backtest_summary"]
    worst = stored["fact_backtest_worst_drawdown"].set_index("strategy_code")
    codes_all = list(stored["dim_strategy"].sort_values("sort_order")["strategy_code"])

    # Independent price table, built again from the raw input rows.
    adj = (inputs["prices"].pivot(index="price_date", columns="ticker", values="adj_close_price")
           .reindex(index=period, columns=tickers))

    def stored_line(code: str) -> pd.DataFrame:
        return daily[daily["strategy_code"] == code].set_index("price_date")

    # ------------------------------------------------------------------ B01
    sec = inputs["securities"]
    tw = sec.loc[sec["role"] == "HOLDING", "target_weight"]
    check("B01", "Target weights: 12 holdings, sum = 1 (1e-12)",
          "12 / 1", f"{len(tw)} / {tw.sum():.15g}",
          len(tw) == 12 and abs(tw.sum() - 1.0) <= 1e-12)

    # ------------------------------------------------------------------ B02
    exp_daily = len(codes_all) * len(period)
    one_per_day = not daily.duplicated(["strategy_code", "price_date"]).any()
    dates_ok = all(stored_line(c).index.equals(period) for c in codes_all)
    dup_trades = int(trades.duplicated(["strategy_code", "price_date", "ticker"]).sum())
    check("B02", "Row counts: daily = 5 x days, one row per line per day, no duplicate trades",
          f"{exp_daily} rows, 0 dup", f"{len(daily)} rows, {dup_trades} dup",
          len(daily) == exp_daily and one_per_day and dates_ok and dup_trades == 0
          and len(codes_all) == 5)

    # ------------------------------------------------------------------ B03
    base_idx = daily.loc[daily["price_date"] == base_day, "index_value"]
    check("B03", "Index = 100 on the base day for all 5 lines (1e-12)",
          "5 x 100", f"{len(base_idx)} rows, max diff {_max_abs(base_idx - 100.0):.2g}",
          len(base_idx) == 5 and _max_abs(base_idx - 100.0) <= 1e-12)

    # ------------------------------------------------------------------ B04
    # Headline: positions rebuilt from the STORED trade rows (signed units,
    # running total), valued at adj_close, plus cash = cash_weight x value.
    worst_gap = 0.0
    for code in STRATEGIES:
        t = trades[trades["strategy_code"] == code].copy()
        t["signed"] = np.where(t["side"] == "BUY", t["units"], -t["units"])
        u = (t.pivot_table(index="price_date", columns="ticker", values="signed", aggfunc="sum")
             .reindex(index=period, columns=tickers).fillna(0.0).cumsum())
        line = stored_line(code)
        rebuilt = (u * adj).sum(axis=1) + line["cash_weight"] * line["value"]
        worst_gap = max(worst_gap, _max_abs(rebuilt - line["value"]))
    # 0 and 25 bp: in-memory units and cash.
    for (code, bps), sim in sims.items():
        d = sim["daily"].set_index("price_date")
        rebuilt = (sim["units"] * adj).sum(axis=1) + d["cash"]
        worst_gap = max(worst_gap, _max_abs(rebuilt - d["value"]))
    check("B04", "Value = positions (rebuilt from trades) + cash, every line and day (1e-6 USD)",
          "<= 1e-6", worst_gap, worst_gap <= 1e-6)

    # ------------------------------------------------------------------ B05
    sim = sims[(S1, 0)]
    v = sim["daily"].set_index("price_date")["value"]
    pos_val = sim["units"] * adj
    w_prev = pos_val.div(pos_val.sum(axis=1), axis=0).shift(1)
    rets = adj / adj.shift(1) - 1.0
    r_pred = (w_prev * rets).sum(axis=1).loc[return_days]
    r_sim = (v / v.shift(1) - 1.0).loc[return_days]
    gap = _max_abs(r_pred - r_sim)
    check("B05", "S1 at 0 bp: return = sum of previous-close weights x holding returns (1e-12)",
          "<= 1e-12", gap, gap <= 1e-12)

    # ------------------------------------------------------------------ B06
    s1_const = all((sims[(S1, b)]["units"].iloc[1:] == sims[(S1, b)]["units"].iloc[0]).all().all()
                   for b in COST_LEVELS_BPS)
    check("B06", "S1 units never change after the base day", True, s1_const, s1_const)

    # ------------------------------------------------------------------ B07 / B08 / B09
    gap7, changed8, gap9 = 0.0, 0, 0.0
    for b in COST_LEVELS_BPS:
        sim = sims[(S2, b)]
        d = sim["daily"].set_index("price_date")
        pv = sim["units"] * adj
        w = pv.div(d["value"], axis=0)
        td = d.index[d["is_trade_date"]]
        gap7 = max(gap7, _max_abs(w.loc[td] - targets))
        u = sim["units"]
        same = (u == u.shift(1)).all(axis=1)
        non_trade = ~d["is_trade_date"]
        non_trade.iloc[0] = False                       # base day has no previous row
        changed8 += int((~same[non_trade.to_numpy()]).sum())
        if b == 0:
            gap9 = _max_abs(d.loc[td, "value_pre"] - d.loc[td, "value"])
    check("B07", "S2 post-trade weights = targets on every trade date, all cost levels (1e-9)",
          "<= 1e-9", gap7, gap7 <= 1e-9)
    check("B08", "S2 units unchanged between trade dates, all cost levels",
          "0 days changed", changed8, changed8 == 0)
    check("B09", "S2 at 0 bp: value before = value after rebalancing (1e-9 USD)",
          "<= 1e-9", gap9, gap9 <= 1e-9)

    # ------------------------------------------------------------------ B10 / B11
    gap10, gap11 = 0.0, 0.0
    for (code, b), sim in sims.items():
        t = sim["trades"]
        gap10 = max(gap10, abs(t["cost"].sum() - b / 10_000.0 * t["traded_value"].sum()))
        d = sim["daily"]
        td = d[d["is_trade_date"]]
        gap11 = max(gap11, _max_abs(td["value"] + td["cost_paid"] - td["value_pre"]))
    for code in STRATEGIES:   # same test on the stored headline trades
        t = trades[trades["strategy_code"] == code]
        gap10 = max(gap10, abs(t["cost"].sum() - HEADLINE_BPS / 10_000.0 * t["traded_value"].sum()))
    check("B10", "Total cost = cost rate x total traded value, every strategy and level (1e-9)",
          "<= 1e-9", gap10, gap10 <= 1e-9)
    check("B11", "Value after trades + cost = value before, every trade date (1e-9 USD)",
          "<= 1e-9", gap11, gap11 <= 1e-9)

    # ------------------------------------------------------------------ B12
    # Recompute every signal a different way: pandas rolling() means on the
    # full price history, read on the signal date (t-1).
    adj_full = result["adj_full"]
    sig_dates = result["signal_dates"]
    dec = result["decisions"]
    sma_s = adj_full.rolling(SMA_SHORT).mean()
    sma_l = adj_full.rolling(SMA_LONG).mean()
    alt = pd.DataFrame((sma_s.loc[sig_dates.to_numpy()] > sma_l.loc[sig_dates.to_numpy()]).to_numpy(),
                       index=dec.index, columns=adj_full.columns)
    mism = int((alt[tickers] != dec[tickers]).sum().sum())
    # ...and the stored S3 positions must match the decisions.
    s3_units = sims[(S3, HEADLINE_BPS)]["units"]
    held = s3_units.loc[result["exec_dates"], tickers] > 0
    mism += int((held != dec[tickers]).sum().sum())
    prev_ok = all(adj_full.index.get_loc(e) - adj_full.index.get_loc(s) == 1
                  for e, s in sig_dates.items())
    check("B12", "S3 signals from data up to t-1: rolling() recompute and held positions agree",
          "0 mismatches", mism, mism == 0 and prev_ok)

    # ------------------------------------------------------------------ B13
    # Scramble every price ON OR AFTER each execution date. If the decision
    # used any of those prices it would (almost surely) change.
    rng = np.random.default_rng(6)
    changed13 = 0
    for e in result["exec_dates"]:
        scrambled = adj_full.copy()
        mask = scrambled.index >= e
        scrambled.loc[mask] = scrambled.loc[mask] * rng.uniform(0.2, 5.0, size=scrambled.loc[mask].shape)
        redo, _ = ma_decisions(scrambled, pd.DatetimeIndex([e]))
        changed13 += int((redo.loc[e, tickers] != dec.loc[e, tickers]).sum())
    check("B13", "S3 decisions unchanged when prices on/after each execution date are scrambled",
          "0 changed", changed13, changed13 == 0)

    # ------------------------------------------------------------------ B14
    first_sig = sig_dates.iloc[0]
    hist_days = int((adj_full.index <= first_sig).sum())
    full = bool(adj_full.loc[:first_sig].iloc[-SMA_LONG:].notna().all().all())
    check("B14", "First S3 signal date has >= 200 trading days of history",
          f">= {SMA_LONG}", f"{hist_days} days to {first_sig.date()}", hist_days >= SMA_LONG and full)

    # ------------------------------------------------------------------ B15
    gap15, out_of_range = 0.0, 0
    for b in COST_LEVELS_BPS:
        sim = sims[(S3, b)]
        d = sim["daily"].set_index("price_date")
        cw = d["cash"] / d["value"]
        out_of_range += int(((cw < 0) | (cw > 1)).sum())
        w = (sim["units"] * adj).div(d["value"], axis=0)
        for e in result["exec_dates"]:
            on = dec.loc[e, tickers].to_numpy(dtype=bool)
            expected_w = np.where(on, targets.to_numpy(), 0.0)
            gap15 = max(gap15, _max_abs(w.loc[e, tickers].to_numpy() - expected_w),
                        abs(cw.loc[e] - targets.to_numpy()[~on].sum()))
    check("B15", "S3 cash weight in [0, 1]; post-trade weights = target or 0 (1e-9)",
          "0 out of range, <= 1e-9", f"{out_of_range}, {gap15:.2g}",
          out_of_range == 0 and gap15 <= 1e-9)

    # ------------------------------------------------------------------ B16
    same16 = True
    for code in STRATEGIES:
        def decision_fingerprint(b):
            sim = sims[(code, b)]
            td = tuple(sim["daily"].loc[sim["daily"]["is_trade_date"], "price_date"])
            held_sets = tuple(tuple(sim["units"].columns[sim["units"].loc[e] > 0]) for e in td)
            return td, held_sets
        fps = [decision_fingerprint(b) for b in COST_LEVELS_BPS]
        same16 = same16 and all(fp == fps[0] for fp in fps)
    check("B16", "Same trade dates and same holdings held at 0, 10 and 25 bp",
          True, same16, same16)

    # ------------------------------------------------------------------ B17
    # Recompute headline metrics from the STORED daily table with numpy.
    rf = port["rf_daily"].loc[return_days].to_numpy()
    r_spy = port["r_spy"].loc[return_days].to_numpy()
    gap17, gap17_beta, gap17_dd = 0.0, 0.0, 0.0
    for code in codes_all:
        line = stored_line(code)
        idx = line["index_value"].to_numpy()
        r = line["daily_return"].loc[return_days].to_numpy()
        tot = idx[-1] / 100.0 - 1.0
        ann = (1.0 + tot) ** (yr / n) - 1.0
        vol = np.std(r, ddof=1) * np.sqrt(yr)
        rf_ann = (1.0 + rf.mean()) ** yr - 1.0
        mdd = (idx / np.maximum.accumulate(idx) - 1.0).min()
        beta = np.polyfit(r_spy - rf, r - rf, 1)[0]      # slope of a least-squares line
        bps = HEADLINE_BPS if code in STRATEGIES else 0
        s = summ[(summ["strategy_code"] == code) & (summ["cost_bps"] == bps)].set_index("metric_key")["value"]
        for key, val in [("total_return", tot), ("annualized_return", ann),
                         ("annualized_volatility", vol), ("avg_rf_annual", rf_ann),
                         ("sharpe_ratio", (ann - rf_ann) / vol), ("max_drawdown", mdd)]:
            gap17 = max(gap17, abs(s[key] - val))
        gap17_beta = max(gap17_beta, abs(s["beta"] - beta))
        gap17_dd = max(gap17_dd, abs(worst.loc[code, "depth"] - mdd))
        if code in STRATEGIES:
            gap17 = max(gap17, abs(s["ending_value"] - line["value"].iloc[-1]),
                        abs(s["total_costs"] - trades.loc[trades["strategy_code"] == code, "cost"].sum()))
    check("B17", "Summary = recomputed from stored daily table (1e-12; beta via polyfit 1e-9; "
                 "worst drawdown depth = max drawdown 1e-12)",
          "<= 1e-12 / 1e-9 / 1e-12", f"{gap17:.2g} / {gap17_beta:.2g} / {gap17_dd:.2g}",
          gap17 <= 1e-12 and gap17_beta <= 1e-9 and gap17_dd <= 1e-12)

    # ------------------------------------------------------------------ B18
    max_dd = float(daily["drawdown"].max())
    check("B18", "Drawdown <= 0 everywhere", "<= 0", max_dd, max_dd <= 0)

    # ------------------------------------------------------------------ B19
    bad = 0
    sim_rows = daily[daily["strategy_code"].isin(STRATEGIES)]
    ref_rows = daily[~daily["strategy_code"].isin(STRATEGIES)]
    bad += int(sim_rows[["value", "index_value", "cum_return", "drawdown",
                         "cash_weight", "cost_paid"]].isna().sum().sum())
    bad += int(daily["daily_return"].isna().ne(daily["price_date"] == base_day).sum())
    bad += int(ref_rows[["cash_weight", "cost_paid"]].notna().sum().sum())
    bad += int(daily.loc[daily["strategy_code"] == ACTUAL, "value"].isna().sum())
    bad += int(daily.loc[daily["strategy_code"] == SPY_REF, "value"].notna().sum())
    bad += int(ref_rows[["index_value", "cum_return", "drawdown"]].isna().sum().sum())
    bad += int(trades.isna().sum().sum()) + int(summ.isna().sum().sum())
    bad += int((worst["recovery_date"].isna() != ~worst["recovered"]).sum())
    bad += int((worst["days_peak_to_recovery"].isna() != ~worst["recovered"]).sum())
    check("B19", "No NULLs except the documented ones", "0", bad, bad == 0)

    # ------------------------------------------------------------------ B20
    act, spy = stored_line(ACTUAL), stored_line(SPY_REF)
    pairs = [
        (act["index_value"], port["index_p"]), (act["drawdown"], port["dd_p"]),
        (act["value"], port["market_value"]),
        (act["daily_return"].loc[return_days], port["r_p"].loc[return_days]),
        (spy["index_value"], port["index_spy"]), (spy["drawdown"], port["dd_spy"]),
        (spy["daily_return"].loc[return_days], port["r_spy"].loc[return_days]),
    ]
    gap20 = max(_max_abs(a - b) for a, b in pairs)
    check("B20", "ACTUAL and SPY rows = fact_daily_portfolio (1e-12)", "<= 1e-12", gap20, gap20 <= 1e-12)

    # ------------------------------------------------------------------ B21
    # Expected count from the NYSE calendar, independent of dim_date:
    # every month from the base month on whose real last trading day falls
    # after the base day and on or before the last price date.
    expected_dates = []
    y, m = base_day.year, base_day.month
    while True:
        me = pd.Timestamp(true_last_trading_day_of_month(date(y, m, 1)))
        if me > last_day:
            break
        if me > base_day:
            expected_dates.append(me)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    td = result["trade_dates"]
    in_data = set(pd.to_datetime(cal["price_date"]))
    check("B21", "Trade dates = real month-ends (NYSE calendar); last price date excluded unless real",
          f"{len(expected_dates)} dates, last {expected_dates[-1].date()}",
          f"{len(td)} dates, last {td[-1].date()}",
          list(td) == expected_dates and all(d in in_data for d in td)
          and (last_day not in td or last_day in expected_dates))

    # ------------------------------------------------------------------ B22
    a_sum = inputs["analysis_summary"].set_index("metric_key")
    gap22 = 0.0
    for key in ("total_return", "annualized_return", "annualized_volatility", "avg_rf_annual",
                "sharpe_ratio", "max_drawdown", "beta", "beta_raw"):
        for code, col in ((ACTUAL, "portfolio_value"), (SPY_REF, "spy_value")):
            mine = summ[(summ["strategy_code"] == code) & (summ["metric_key"] == key)]["value"].iloc[0]
            gap22 = max(gap22, abs(mine - a_sum.loc[key, col]))
    check("B22", "ACTUAL and SPY summary values = analysis_summary (1e-12)", "<= 1e-12", gap22, gap22 <= 1e-12)

    return results
