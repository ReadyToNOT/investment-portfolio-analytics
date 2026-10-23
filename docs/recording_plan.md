# Screen recording plan (about 1 minute 40 seconds)

Sample portfolio, educational project, not investment advice.

## Setup

- Open `dashboard/portfolio_analytics.pbix`. Collapse the Filters, Visualizations and Data panes, and set **View → Page view → Fit to page**.
- Start on Executive Summary with the date slicer at the full range.
- Record with the Xbox Game Bar: press **Windows key + Alt + R** to start and stop. It records the active window and saves an .mp4 to `Videos\Captures`. You can trim the start and end in the Photos app or Clipchamp.
- Do one silent practice run first. Speak slowly, and move the mouse to what you're talking about.

## Script

| Time | Page and action | What to say |
|---|---|---|
| 0:00-0:12 | Executive Summary | "I wanted to know whether a sample 12-holding portfolio beat the S&P 500 after accounting for risk. Over about three years it returned 72% against SPY's 87%, so it trailed by 15 points." |
| 0:12-0:25 | Point at the volatility, Sharpe and drawdown cards | "But it took much less risk: 11% volatility versus 15%, and a worst drop of about 13% versus 19%. So its Sharpe ratio was higher, 1.43 against 1.27." |
| 0:25-0:35 | Drag the date slicer to 2024 only, then reset it | "Everything responds to the date range. In 2024 alone, the portfolio made 16% versus SPY's 25%." |
| 0:35-0:48 | Holdings & Allocation | "JPMorgan grew to 14% of the portfolio against a 10% target, the largest drift. The portfolio is still fairly spread out: an effective 10.5 holdings out of 12." |
| 0:48-1:00 | Risk, drawdown chart | "Both fell from February to April 2025. The portfolio fell less but took a few more days to recover." |
| 1:00-1:12 | Attribution | "JPMorgan contributed the most return, and UnitedHealth was the only drag. Technology took 27% of the risk for 20% of the return." |
| 1:12-1:27 | Strategy Backtest | "I also tested three rules, written down before I looked at any results. Monthly rebalancing beat buy-and-hold slightly, 77% versus 73% after costs. But that's one three-year market path, so I treat it as a description of history, not proof." |
| 1:27-1:40 | Notes | "The data pipeline is Python and PostgreSQL. Power BI only aggregates stored results, and 106 automated checks plus three hand checks in Excel back every number. It's a fictional sample, not investment advice." |

All numbers come from the README and the dashboard (data through 2026-10-16). If the data is refreshed, update the script.
