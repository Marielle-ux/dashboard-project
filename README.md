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

## Deployment (Streamlit Community Cloud)

### Step-by-step

1. **Merge the PR** into `main` on GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io) → **Sign in with GitHub**.
3. Click **New app**.
4. Select:
   - **Repository:** `Marielle-ux/dashboard-project`
   - **Branch:** `main`
   - **Main file path:** `app.py`
5. Click **Advanced settings** → paste your secrets (see below).
6. Click **Deploy**.

The app will be live at a permanent URL like `https://your-app.streamlit.app`.

### Secrets (required for full functionality)

In the Streamlit Cloud dashboard, go to **Settings → Secrets** and paste
the TOML below. The app reads everything via `st.secrets`.

```toml
# Meta Ads API
META_ACCESS_TOKEN = "EAAXn3YbFKBY..."
META_API_VERSION = "v21.0"

# Optional — only needed if you want to refresh long-lived tokens.
# META_APP_ID = "1234567890"
# META_APP_SECRET = "abcdef0123456789abcdef0123456789"

# Ad account IDs — TOML array (Streamlit native list format)
META_AD_ACCOUNT_IDS = [
  "act_844229314275496",
  "act_719853653795521",
  "act_2342025859327675",
]

# Google Sheets — TOML array of spreadsheet titles to auto-load
GOOGLE_SPREADSHEET_NAMES = [
  "Sheet Name 1",
  "Sheet Name 2",
  "Sheet Name 3",
]
GOOGLE_HEADER_ROW = "3"

# Google Service Account credentials — paste the FULL JSON key as a
# single string. Triple quotes preserve newlines inside private_key.
GOOGLE_CREDENTIALS_JSON = """
{
  "type": "service_account",
  "project_id": "your-project-id",
  "private_key_id": "your-key-id",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
  "client_email": "your-sa@your-project.iam.gserviceaccount.com",
  "client_id": "123456789",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/...",
  "universe_domain": "googleapis.com"
}
"""
```

A `[google_credentials]` TOML table is still supported as an
alternative to `GOOGLE_CREDENTIALS_JSON` — provide exactly one.

See `.streamlit/secrets.toml.example` for a complete template.

The app works without secrets — Meta Ads and Google Sheets sections
will show "Not configured" and all other features (upload, city data,
charts, filters, export) work normally. A **Configuration / Debug**
expander in the sidebar shows which secrets were loaded
(True/False only — no values are exposed).

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
4. Set `META_ACCESS_TOKEN` and `META_AD_ACCOUNT_IDS` (comma-separated locally,
   TOML array in Streamlit secrets) in `.env` or Streamlit secrets.

### Google Sheets

1. Create a **Service Account** in Google Cloud Console.
2. Enable the **Google Sheets API** and **Google Drive API**.
3. Download the JSON key. Locally, place it as `google_credentials.json` (or
   set `GOOGLE_CREDENTIALS_FILE`). On Streamlit Cloud, paste the entire JSON
   contents into the `GOOGLE_CREDENTIALS_JSON` secret.
4. Share each spreadsheet with the service account email (found in the JSON as `client_email`).
5. Set `GOOGLE_SPREADSHEET_NAMES` in `.env` — comma-separated list of spreadsheet titles to auto-load.

The dashboard validates credentials on startup and shows per-spreadsheet connection status:
- **Connected** — credentials valid and APIs enabled
- **API disabled** — enable Google Drive / Sheets API in Cloud Console
- **Permission denied** — share the spreadsheet with the service account
- **Not found** — check the spreadsheet name matches exactly

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
