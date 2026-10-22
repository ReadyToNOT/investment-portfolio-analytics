STAGE 8 KICKOFF: Investment Portfolio Analytics (polish, README, publish, resume, interview prep)

You're picking up a project already in progress. The Project instructions
(working rules, the 8 stages, the five business questions) still apply in full.
Stages 1 to 7 are done. Read all of this before doing anything.

========================================================================
1. HOW I WORK (Jacob)
========================================================================
- Complete beginner in Power BI, dashboards, Git and GitHub. Explain every
  step click by click, in plain language, defining each new term the first
  time. Small checkable steps; after each, tell me what I should see, then wait.
- Terminal commands ONE PER LINE (PyCharm terminal = PowerShell).
- If this chat is linked to my computer, read/write files in
  C:\Users\jacob\portfolio-analytics yourself and list every file changed.
- No invented results: every number must come from our runs (below) or be
  labeled expected/assumption. Not investment advice.

========================================================================
2. STATE AT THE END OF STAGE 7 (2026-10-22)
========================================================================
Repo: C:\Users\jacob\portfolio-analytics. Pipeline and checks unchanged from
Stage 6 (34 raw, 28 model, 22 analysis, 22 backtest checks, all PASS on 2026-10-21).

Power BI file: dashboard/portfolio_analytics.pbix (Import mode, PostgreSQL
localhost / portfolio_analytics). 14 tables, 11 one-to-many single-direction
relationships, dim_date marked as date table, report filters
is_portfolio_period = TRUE and role = HOLDING. Details: docs/powerbi_model.md.
All measures with full DAX: docs/dax_measures.md.

Pages (all built and checked against stored results):
 1 Executive Summary - KPI cards portfolio + SPY, growth of 100 (rebased), date slicer
 2 Holdings & Allocation - concentration cards, holdings table, sector treemap, actual vs target bars
 3 Risk - beta card, rolling 30/90-day vol, drawdown area, 5 worst drawdowns per series,
   correlation matrix, risk share by sector (historical vs current)
 4 Attribution - contribution waterfalls by holding and sector, return share vs risk share
 5 Strategy Backtest - growth lines per strategy, headline matrix, cost sensitivity,
   worst drawdown per strategy, rules, assumptions (no date slicer)
 6 Notes - about, data, pipeline, method, assumptions, dim_date month-end quirk,
   limitations, disclaimer, "Data through 2026-10-16" card
 7 Checks - 11/11 DAX measures PASS vs analysis_summary (largest diff 1.4E-14);
   2024 total return DAX 0.1635132256 = SQL 0.16351322560664516 (252 days);
   contribution sums diff 1.33E-15 (full) and 1.83E-15 (2024); MSFT drift hand check
   -0.0036088 matches. To be HIDDEN in Stage 8.
Colors: Portfolio/Actual #1F6FB2, SPY #9E9E9E, Buy and hold #7B4FA0,
Monthly #E07B39, MA filter #2E9E6A.
Password check: credentials cleared, file reopened, refresh asked for the password
(so it is not stored in the .pbix). Stage 7 committed to git locally (no remote yet).

========================================================================
3. RESULTS (all from our runs; exact values in analysis_summary / Checks page)
========================================================================
Full period 2023-11-01 to 2026-10-16, 741 return days, 12 holdings + SPY.
                    Portfolio   SPY
Total return        72.14%      87.25%   (excess -15.11 pts)
Annualized return   20.29%      23.78%   (excess -3.49 pts)
Annualized vol      11.11%      15.26%
Sharpe              1.43        1.27
Max drawdown        -12.80%     -18.76%
Beta vs SPY         0.51        1.00
2024 only: portfolio 16.35% vs SPY 24.89%; vol 9.30% vs 12.57%.
Worst drawdown (both): peak 2025-02-19, trough 2025-04-08. Recovery: portfolio
2025-07-03 (59 trading days trough to recovery, 93 peak to recovery), SPY
2025-06-26 (54 and 88). Portfolio fell less but recovered slightly slower.
Contribution (pct points of 72.14): JPM 14.63 largest; UNH -1.06 only negative
(UNH own return -19.59%). By sector: Financials 23.25, Technology 14.49,
Energy 14.23, Health Care 10.22, Consumer Staples 9.96.
Share of return vs share of risk (full period): Financials 32.2% vs 33.6%,
Technology 20.1% vs 26.5%, Energy 19.7% vs 14.7%, Health Care 14.2% vs 13.3%,
Consumer Staples 13.8% vs 11.9%.
Concentration on 2026-10-16: effective holdings 10.5, top-5 share 56.18%,
largest drift JPM +4.28 pts (UNH -3.84, AAPL -3.78). Value $204,545; net contributions $133,299.49.
Backtest (10 bp): Buy and hold 73.30% / Sharpe 1.43 / MaxDD -13.07%;
Monthly rebalance 76.86% / 1.53 / -11.78% (420 trades, $292.37 costs);
50/200 MA filter 36.54% / 0.80 / -11.85% (avg cash 27.2%, 225 trading days peak
to recovery). Cost sensitivity 0/10/25 bp: B&H 73.30/73.30/73.30, Monthly
77.12/76.86/76.49, MA 37.30/36.54/35.42. Guardrails: one ~3-year path, no
significance test, survivorship/hindsight, not advice.

========================================================================
4. STAGE 8 TO-DO (target Sunday Nov 15, 2026; ~6-8 h/week)
========================================================================
a. Outstanding from earlier stages: hand checks 1-3 in docs/reconciliation.md are
   still blank (AAPL value, r_p on 2024-05-02, S2 rebalance 2023-11-30). Walk me
   through them in Excel, click by click.
b. Dashboard polish: hide Checks page; align and size visuals; treemap and drawdown
   colors to palette; consistent titles; Notes page text boxes aligned; check
   every page opens on the full date range.
c. README.md: business question and top finding with its number FIRST, then data,
   method, results, limitations, how to reproduce (refresh steps in
   docs/powerbi_model.md), screenshots.
d. Screenshots of each page into docs/ (or dashboard/screenshots/) and a plan for
   a 1-2 minute screen recording.
e. GitHub: create the repo, connect the remote, push; confirm .env is not tracked
   and the .pbix is under GitHub's size limit.
f. Resume bullet with every blank filled from the results above.
g. Interview prep: question I started with, one surprising result, one
   limitation, what I would do next.
