# Marketing Analytics Dashboard

Unified Streamlit dashboard that merges **Meta Ads Manager** campaign data with
**Google Sheets** and **Excel/CSV** reports into a single analytics view.

## Features

- **Meta Ads API integration** – automatically fetch spend, impressions, CPM, CPC, CTR, clicks, and conversions.
- **Google Sheets connector** – read report data from any shared spreadsheet.
- **Excel / CSV upload** – drag-and-drop file upload inside the dashboard.
- **Column normalization** – maps inconsistent names (English & Russian) to a canonical schema.
- **Data cleaning** – handles missing values, duplicates, and type coercion.
- **Reusable ETL pipeline** – `etl/pipeline.py` orchestrates extract → normalize → clean → merge → load.
- **SQLite persistence** – merged results are stored locally for fast reloads.
- **Interactive visualizations** – Plotly charts with date range, source, campaign, and city filters.

## Project Structure

```
dashboard-project/
├── app.py                  # Streamlit dashboard
├── config.py               # Centralized settings (reads .env)
├── create_db.py            # Original DB seed script
├── etl/
│   ├── meta_ads.py         # Meta Marketing API client
│   ├── google_sheets.py    # gspread loader
│   ├── excel_loader.py     # Excel / CSV reader
│   ├── normalizer.py       # Column name mapping & type coercion
│   ├── cleaner.py          # Missing values & dedup
│   ├── merger.py           # Merge / concat logic
│   └── pipeline.py         # ETL orchestrator
├── db/
│   └── database.py         # SQLite helpers
├── .env.example            # Template for credentials
├── .streamlit/
│   └── config.toml         # Streamlit theme & server settings
└── requirements.txt
```

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy and fill in your credentials
cp .env.example .env
# edit .env with your Meta Ads token, ad account ID, etc.

# 3. Run the dashboard
streamlit run app.py
```

## Configuration

All credentials and settings live in environment variables (or a `.env` file).
See `.env.example` for the full list.

### Meta Ads API

1. Create an app at <https://developers.facebook.com/apps/>.
2. Add the **Marketing API** product.
3. Generate a long-lived access token with `ads_read` permission.
4. Set `META_ACCESS_TOKEN` and `META_AD_ACCOUNT_ID` in `.env`.

### Google Sheets

1. Create a **Service Account** in Google Cloud Console.
2. Enable the **Google Sheets API** and **Google Drive API**.
3. Download the JSON key and place it as `google_credentials.json` (or set `GOOGLE_CREDENTIALS_FILE`).
4. Share your spreadsheet with the service account email.

## Database Schema

The unified analytics table follows this canonical structure:

| Column          | Type    | Description              |
|-----------------|---------|--------------------------|
| `date`          | TEXT    | Report date              |
| `campaign_name` | TEXT    | Campaign name            |
| `ad_set`        | TEXT    | Ad set / ad group        |
| `source`        | TEXT    | Data source / platform   |
| `city`          | TEXT    | City / region            |
| `spend`         | REAL    | Ad spend                 |
| `impressions`   | INTEGER | Number of impressions    |
| `cpm`           | REAL    | Cost per 1 000 impressions |
| `cpc`           | REAL    | Cost per click           |
| `ctr`           | REAL    | Click-through rate       |
| `clicks`        | INTEGER | Number of clicks         |
| `conversions`   | INTEGER | Conversion count         |
| `revenue`       | REAL    | Revenue                  |

## ETL Pipeline

```python
from etl.pipeline import run_pipeline

# Run with uploaded reports
unified_df = run_pipeline(
    report_dfs=[my_excel_df, my_sheets_df],
    start_date=date(2026, 5, 1),
    end_date=date(2026, 5, 25),
)
```

The pipeline is idempotent: re-running it replaces the `unified_analytics` table
with the latest data.
