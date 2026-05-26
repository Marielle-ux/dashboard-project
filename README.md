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
- **SQLite persistence** – merged results are stored in SQLite and auto-loaded on restart.
- **Upload persistence** – uploaded files are saved to `uploads/` and automatically reloaded.
- **Interactive visualizations** – Plotly charts with date range, source, campaign, and city filters.

## Project Structure

```
dashboard-project/
├── app.py                  # Streamlit dashboard
├── config.py               # Centralized settings (reads .env / st.secrets)
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
├── uploads/                # Persistent storage for uploaded files
├── .env.example            # Template for credentials
├── .streamlit/
│   └── config.toml         # Streamlit theme & server settings
└── requirements.txt
```

## Quick Start (Local)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy and fill in your credentials
cp .env.example .env
# edit .env with your Meta Ads token, ad account ID, etc.

# 3. Run the dashboard
streamlit run app.py
```

## Deployment (Streamlit Cloud)

### One-click deploy

1. Push this repo to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in.
3. Click **New app** → select this repo → branch `main` → main file `app.py`.
4. Click **Deploy**.

### Secrets (optional)

If you want Meta Ads or Google Sheets integration on the deployed app, add
secrets in the Streamlit Cloud dashboard (**Settings → Secrets**):

```toml
META_ACCESS_TOKEN = "your-token"
META_AD_ACCOUNT_ID = "act_123456789"
META_APP_ID = ""
META_APP_SECRET = ""
META_API_VERSION = "v21.0"
GOOGLE_CREDENTIALS_FILE = "google_credentials.json"
SYNC_INTERVAL_MINUTES = "30"
```

The app works without these secrets — Meta Ads and Google Sheets sections
will show "Not configured" and all other features (upload, city data,
charts, filters, export) work normally.

### Data persistence on Streamlit Cloud

- **Uploaded files** are saved to the `uploads/` directory and automatically
  reloaded when the app restarts.
- **Merged data** is persisted to `dashboard.db` (SQLite) after every sync.
- **Note:** Streamlit Cloud may reset the filesystem on redeployment. For
  long-term persistence, consider connecting an external database.

## Configuration

All credentials and settings live in environment variables (or a `.env` file).
On Streamlit Cloud, use **Settings → Secrets** instead.
See `.env.example` for the full list.

### Meta Ads API

1. Create an app at <https://developers.facebook.com/apps/>.
2. Add the **Marketing API** product.
3. Generate a long-lived access token with `ads_read` permission.
4. Set `META_ACCESS_TOKEN` and `META_AD_ACCOUNT_ID` in `.env` or Streamlit secrets.

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
