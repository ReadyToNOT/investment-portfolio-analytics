# Investment Portfolio Analytics

> Educational project using a clearly labeled **sample** portfolio. Not investment advice.

Status: in progress. The business question, top finding and full write-up will be added at the end of the project.

## Project layout

| Folder | Purpose |
|---|---|
| `data/raw` | Raw downloads exactly as received |
| `data/processed` | Cleaned data and lookup tables |
| `sql` | Schema, views and validation queries |
| `src` | Python scripts (download, load, analysis) |
| `dashboard` | Power BI file |
| `docs` | Notes, screenshots, methodology |

## Setup

1. Create a virtual environment and run `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in your PostgreSQL details
3. Run `python src/check_setup.py`