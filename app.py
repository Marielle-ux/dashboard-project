"""
Marketing Analytics Dashboard
Unified view of Meta Ads + Google Sheets / Excel reports.
"""

import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from config import settings, BASE_DIR
from db.database import list_tables, load_dataframe, save_dataframe
from etl.excel_loader import load_uploaded_file, load_file
from etl.google_sheets import (
    check_connection_status as check_gsheets_connection,
    load_all_configured_spreadsheets,
    load_sheet,
)
from etl.normalizer import (
    coerce_numeric_columns,
    normalize_columns,
    standardize_date_column,
)
from etl.cleaner import clean_dataframe, remove_duplicates
from etl.merger import concat_datasets, merge_datasets
from etl.meta_ads import fetch_campaign_insights, check_account_status
from etl.pipeline import load_cached_data, run_pipeline
from sync_engine import build_unified_analytics
from dashboard_views import (
    render_overview_kpis,
    render_campaign_comparison,
    render_time_series,
    render_correlation_view,
)

# Persistent directory for uploaded files (survives restarts)
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Marketing Analytics Dashboard",
    page_icon="\U0001f4ca",
    layout="wide",
)

st.title("Marketing Analytics Dashboard")

# ---------------------------------------------------------------------------
# Sidebar – data source controls
# ---------------------------------------------------------------------------
st.sidebar.header("Data Sources")

# Date range
default_start = date.today() - timedelta(days=30)
date_range = st.sidebar.date_input(
    "Date range",
    value=(default_start, date.today()),
    max_value=date.today(),
)
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = default_start, date.today()

# Meta Ads toggle
use_meta = st.sidebar.checkbox(
    "Fetch Meta Ads data",
    value=settings.meta_ads.is_configured,
    disabled=not settings.meta_ads.is_configured,
)
if not settings.meta_ads.is_configured:
    st.sidebar.caption(
        "Set META_ACCESS_TOKEN and META_AD_ACCOUNT_IDS in Secrets to enable."
    )
elif settings.meta_ads.ad_account_ids:
    st.sidebar.caption(
        f"{len(settings.meta_ads.ad_account_ids)} ad account(s) configured"
    )

# Google Sheets
gs_cfg = settings.google_sheets
gs_has_configured_sheets = bool(gs_cfg.is_configured and gs_cfg.spreadsheet_names)
use_gsheets = st.sidebar.checkbox(
    "Load Google Sheets",
    value=gs_has_configured_sheets,
    disabled=not gs_cfg.is_configured,
)
if not gs_cfg.is_configured:
    st.sidebar.caption("Add Google credentials in Secrets to enable.")
elif gs_cfg.spreadsheet_names:
    st.sidebar.caption(
        f"{len(gs_cfg.spreadsheet_names)} spreadsheet(s) configured"
    )
gsheet_name = ""
gsheet_worksheet = ""
if use_gsheets:
    gsheet_name = st.sidebar.text_input(
        "Additional spreadsheet name (optional)"
    )
    gsheet_worksheet = st.sidebar.text_input("Worksheet (optional)")

# File uploads
uploaded_files = st.sidebar.file_uploader(
    "Upload Excel / CSV reports",
    type=["xlsx", "xls", "csv", "tsv"],
    accept_multiple_files=True,
)

# Existing city data
use_city_data = st.sidebar.checkbox("Include existing city data", value=True)
city_selection = []
if use_city_data:
    city_selection = st.sidebar.multiselect(
        "Cities",
        ["aqtobe", "atyrau", "karaganda"],
        default=["aqtobe", "atyrau", "karaganda"],
    )

# ---------------------------------------------------------------------------
# Auto-sync (periodic refresh)
# ---------------------------------------------------------------------------
AUTO_SYNC_SECONDS = settings.sync_interval_minutes * 60  # default 15 min

if "last_sync_time" not in st.session_state:
    st.session_state["last_sync_time"] = 0.0

time_since_sync = time.time() - st.session_state["last_sync_time"]
auto_sync_due = time_since_sync >= AUTO_SYNC_SECONDS and st.session_state["last_sync_time"] > 0

if auto_sync_due:
    st.toast("Auto-syncing data (every {0} min)…".format(settings.sync_interval_minutes))

st.sidebar.caption(
    f"Auto-sync every {settings.sync_interval_minutes} min"
)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
run_sync = st.sidebar.button("Sync Data", type="primary")


@st.cache_data(ttl=settings.sync_interval_minutes * 60)
def fetch_meta(s: date, e: date) -> pd.DataFrame:
    return fetch_campaign_insights(start_date=s, end_date=e)


@st.cache_data(ttl=settings.sync_interval_minutes * 60)
def fetch_gsheet(name: str, worksheet: str) -> pd.DataFrame:
    ws = worksheet if worksheet else None
    return load_sheet(name, worksheet_name=ws)


def load_city_table(table: str) -> pd.DataFrame:
    df = load_dataframe(table)
    if not df.empty:
        df = normalize_columns(df)
        df = standardize_date_column(df)
        df = coerce_numeric_columns(df)
        if "source" not in df.columns:
            df["source"] = table
        if "city" not in df.columns:
            df["city"] = table.capitalize()
    return df


# ---------------------------------------------------------------------------
# Helpers – persist and reload uploaded files
# ---------------------------------------------------------------------------
def _save_uploaded_file(uploaded_file) -> Path:
    """Save an uploaded file to the persistent uploads/ directory."""
    dest = UPLOADS_DIR / uploaded_file.name
    dest.write_bytes(uploaded_file.getvalue())
    return dest


def _load_saved_uploads() -> list[pd.DataFrame]:
    """Load all previously-saved uploads from disk."""
    dfs: list[pd.DataFrame] = []
    for fp in sorted(UPLOADS_DIR.iterdir()):
        if fp.suffix.lower() in {".xlsx", ".xls", ".csv", ".tsv"}:
            udf = load_file(fp)
            if not udf.empty:
                udf = normalize_columns(udf)
                udf = standardize_date_column(udf)
                udf = coerce_numeric_columns(udf)
                if "source" not in udf.columns:
                    udf["source"] = f"upload:{fp.name}"
                dfs.append(udf)
    return dfs


# Gather all sources
all_dfs: list[pd.DataFrame] = []

should_load = run_sync or auto_sync_due or "unified_data" not in st.session_state

if run_sync or auto_sync_due:
    # Clear cached API data so fresh results are fetched
    fetch_meta.clear()
    fetch_gsheet.clear()

if should_load:
    with st.spinner("Loading data ..."):
        # Meta Ads
        if use_meta and settings.meta_ads.is_configured:
            meta_df = fetch_meta(start_date, end_date)
            if not meta_df.empty:
                all_dfs.append(meta_df)

        # Google Sheets — auto-load configured spreadsheets
        if use_gsheets and gs_has_configured_sheets:
            gs_dfs = load_all_configured_spreadsheets()
            for gs_df in gs_dfs:
                gs_df = normalize_columns(gs_df)
                gs_df = standardize_date_column(gs_df)
                gs_df = coerce_numeric_columns(gs_df)
                all_dfs.append(gs_df)

        # Google Sheets — additional manually specified spreadsheet
        if use_gsheets and gsheet_name:
            gs_df = fetch_gsheet(gsheet_name, gsheet_worksheet)
            if not gs_df.empty:
                gs_df = normalize_columns(gs_df)
                gs_df = standardize_date_column(gs_df)
                gs_df = coerce_numeric_columns(gs_df)
                if "source" not in gs_df.columns:
                    gs_df["source"] = "google_sheets"
                all_dfs.append(gs_df)

        # Newly uploaded files – save to disk for persistence
        for uf in uploaded_files:
            _save_uploaded_file(uf)

        # Load ALL saved uploads (current + previous sessions)
        all_dfs.extend(_load_saved_uploads())

        # Existing city tables
        if use_city_data:
            for city in city_selection:
                cdf = load_city_table(city)
                if not cdf.empty:
                    all_dfs.append(cdf)

        # Clean each source individually (before concat) to avoid
        # cross-schema NaN columns causing valid rows to be dropped.
        all_dfs = [clean_dataframe(d) for d in all_dfs]

        # Merge
        if all_dfs:
            unified = concat_datasets(all_dfs)
            unified = remove_duplicates(unified)
        else:
            unified = load_cached_data()

        # Standardize date column after merge (Meta Ads returns
        # datetime.date objects, Google Sheets returns Timestamps —
        # concat produces mixed-type object column).
        if "date" in unified.columns:
            unified["date"] = pd.to_datetime(unified["date"], errors="coerce")

        # Persist unified data to SQLite so it survives restarts
        if not unified.empty:
            save_dataframe(unified, table_name="unified_analytics")

        st.session_state["unified_data"] = unified
        st.session_state["last_sync_time"] = time.time()
        st.session_state["last_sync_dt"] = datetime.now().strftime("%H:%M:%S")

df = st.session_state.get("unified_data", pd.DataFrame())

# ---------------------------------------------------------------------------
# Connection status — live validation (multi-account)
# ---------------------------------------------------------------------------
def _check_all_meta_accounts() -> list[tuple[str, str, str]]:
    """Return [(account_id, status, detail), ...] for each configured account."""
    cfg = settings.meta_ads
    if not cfg.access_token:
        return [("", "No token", "Set META_ACCESS_TOKEN in Secrets")]
    if not cfg.ad_account_ids:
        return [("", "No accounts", "Set META_AD_ACCOUNT_IDS in Secrets")]
    results: list[tuple[str, str, str]] = []
    for aid in cfg.ad_account_ids:
        status, detail = check_account_status(aid)
        results.append((aid, status, detail))
        logger.info("Meta Ads %s: %s (%s)", aid, status, detail)
    return results


def _check_gsheets_status() -> tuple[str, str]:
    """Validate Google Sheets connectivity. Returns (status, detail)."""
    return check_gsheets_connection()


account_statuses = _check_all_meta_accounts()
gs_status, gs_detail = _check_gsheets_status()

connected_count = sum(1 for _, s, _ in account_statuses if s == "Connected")
total_accounts = len(settings.meta_ads.ad_account_ids)

meta_rows = len(df[df["source"] == "meta_ads"]) if "source" in df.columns and not df.empty else 0
gs_rows = len(df[df["source"] == "google_sheets"]) if "source" in df.columns and not df.empty else 0

col1, col2, col3 = st.columns(3)
with col1:
    if total_accounts == 0:
        st.metric("Meta Ads API", "Not configured")
        st.caption("Set META_AD_ACCOUNT_IDS in Secrets")
    else:
        st.metric("Meta Ads API", f"{connected_count}/{total_accounts} connected")
        for aid, status, detail in account_statuses:
            icon = "\u2705" if status == "Connected" else "\u274c"
            label = detail if status == "Connected" else f"{status}: {detail}"
            st.caption(f"{icon} {aid}: {label}")
with col2:
    gs_icon = "\u2705" if gs_status == "Connected" else "\u274c"
    st.metric("Google Sheets", gs_status)
    if gs_status == "Connected":
        st.caption(f"{gs_icon} {gs_detail}")
        if settings.google_sheets.spreadsheet_names:
            st.caption(
                f"{len(settings.google_sheets.spreadsheet_names)} spreadsheet(s) configured"
            )
    else:
        st.caption(f"{gs_icon} {gs_detail}")
with col3:
    delta_parts = []
    if meta_rows:
        delta_parts.append(f"{meta_rows} from Meta Ads")
    if gs_rows:
        delta_parts.append(f"{gs_rows} from Google Sheets")
    delta_text = ", ".join(delta_parts) if delta_parts else None
    st.metric("Total rows loaded", len(df), delta=delta_text)

# ---------------------------------------------------------------------------
# Debug status (config loaded — no sensitive values)
# ---------------------------------------------------------------------------
with st.expander("Configuration Status", expanded=False):
    dcol1, dcol2 = st.columns(2)
    with dcol1:
        st.markdown("**Meta Ads**")
        st.write(f"- META_ACCESS_TOKEN loaded: **{bool(settings.meta_ads.access_token)}**")
        st.write(f"- META_AD_ACCOUNT_IDS loaded: **{bool(settings.meta_ads.ad_account_ids)}**")
        st.write(f"- Accounts count: **{len(settings.meta_ads.ad_account_ids)}**")
        st.write(f"- API version: **{settings.meta_ads.api_version}**")
    with dcol2:
        st.markdown("**Google Sheets**")
        st.write(f"- Credentials loaded: **{bool(settings.google_sheets.credentials_info)}**")
        st.write(f"- Service account: **{bool(settings.google_sheets.service_account_email)}**")
        st.write(f"- Spreadsheets configured: **{len(settings.google_sheets.spreadsheet_names)}**")
        st.write(f"- Header row: **{settings.google_sheets.header_row}**")

st.divider()

if df.empty:
    st.info(
        "No data loaded yet. Configure your data sources in the sidebar "
        "and click **Sync Data**."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_overview, tab_meta, tab_correlation, tab_reports, tab_data = st.tabs(
    ["Overview", "Meta Ads Metrics", "Correlation", "Reports", "Raw Data"]
)

# ---- Helpers ----
METRIC_COLS = ["spend", "impressions", "cpm", "cpc", "ctr", "clicks", "conversions"]
available_metrics = [m for m in METRIC_COLS if m in df.columns]


def safe_sum(series: pd.Series) -> float:
    return pd.to_numeric(series, errors="coerce").sum()


# Build analytics context via sync engine
analytics = build_unified_analytics(df)
meta_summary = analytics["meta_summary"]
sheets_summary = analytics["sheets_summary"]
correlated = analytics["correlated"]
overview_kpis = analytics["overview_kpis"]

# ======================= TAB: Overview ====================================
with tab_overview:
    # A) Overview KPIs from sync engine
    render_overview_kpis(overview_kpis)

    st.divider()

    # C) Time Series from sync engine
    render_time_series(meta_summary)

    # By source breakdown (original)
    if "source" in df.columns and available_metrics:
        st.subheader("By Source / Platform")
        metric_for_source = st.selectbox(
            "Metric", available_metrics, key="source_metric"
        )
        source_agg = (
            df.groupby("source")[metric_for_source]
            .apply(lambda s: pd.to_numeric(s, errors="coerce").sum())
            .reset_index()
        )
        fig = px.bar(
            source_agg,
            x="source",
            y=metric_for_source,
            title=f"{metric_for_source.upper()} by Source",
            color="source",
        )
        st.plotly_chart(fig, use_container_width=True)

# ======================= TAB: Meta Ads ====================================
with tab_meta:
    st.subheader("Meta Ads Campaign Performance")

    meta_data = df[df["source"] == "meta_ads"] if "source" in df.columns else pd.DataFrame()

    if meta_data.empty:
        st.info("No Meta Ads data available. Configure API credentials to fetch data.")
    else:
        # Account filter
        if "account_name" in meta_data.columns:
            account_names = sorted(meta_data["account_name"].dropna().unique().tolist())
            sel_accounts = st.multiselect(
                "Filter by Ad Account",
                account_names,
                default=account_names,
                key="meta_account_filter",
            )
            if sel_accounts:
                meta_data = meta_data[meta_data["account_name"].isin(sel_accounts)]

        # Campaign breakdown
        if "campaign_name" in meta_data.columns:
            st.markdown("#### Campaign Breakdown")
            group_cols = ["campaign_name"]
            if "account_name" in meta_data.columns:
                group_cols = ["account_name", "campaign_name"]
            campaign_metrics = (
                meta_data.groupby(group_cols)[available_metrics]
                .apply(lambda g: g.apply(pd.to_numeric, errors="coerce").sum())
                .reset_index()
            )
            st.dataframe(campaign_metrics, use_container_width=True)

            # Spend by campaign
            if "spend" in available_metrics:
                color_col = "account_name" if "account_name" in campaign_metrics.columns else None
                fig = px.pie(
                    campaign_metrics,
                    names="campaign_name",
                    values="spend",
                    color=color_col,
                    title="Spend Distribution by Campaign",
                )
                st.plotly_chart(fig, use_container_width=True)

        # By account breakdown
        if "account_name" in meta_data.columns and len(meta_data["account_name"].unique()) > 1:
            st.markdown("#### Spend by Ad Account")
            account_agg = (
                meta_data.groupby("account_name")[available_metrics]
                .apply(lambda g: g.apply(pd.to_numeric, errors="coerce").sum())
                .reset_index()
            )
            st.dataframe(account_agg, use_container_width=True)
            if "spend" in available_metrics:
                fig = px.bar(
                    account_agg,
                    x="account_name",
                    y="spend",
                    title="Spend by Ad Account",
                    color="account_name",
                )
                st.plotly_chart(fig, use_container_width=True)

        # Ad set breakdown
        if "ad_set" in meta_data.columns:
            st.markdown("#### Ad Set Performance")
            adset_metrics = (
                meta_data.groupby("ad_set")[available_metrics]
                .apply(lambda g: g.apply(pd.to_numeric, errors="coerce").sum())
                .reset_index()
            )
            st.dataframe(adset_metrics, use_container_width=True)

# ======================= TAB: Correlation =================================
with tab_correlation:
    # B) Campaign Comparison Table
    render_campaign_comparison(correlated)

    st.divider()

    # D) Correlation View
    render_correlation_view(correlated)

# ======================= TAB: Reports =====================================
with tab_reports:
    st.subheader("Uploaded & Google Sheets Reports")

    non_meta = (
        df[df["source"] != "meta_ads"] if "source" in df.columns else df.copy()
    )

    if non_meta.empty:
        st.info("No report data. Upload files or connect Google Sheets.")
    else:
        sources = non_meta["source"].unique() if "source" in non_meta.columns else ["all"]
        for src in sources:
            with st.expander(f"Source: {src}", expanded=True):
                subset = (
                    non_meta[non_meta["source"] == src]
                    if "source" in non_meta.columns
                    else non_meta
                )
                st.dataframe(subset, use_container_width=True)
                st.caption(f"{len(subset)} rows")

    # Data completeness
    st.markdown("#### Data Completeness")
    missing = df.isnull().sum().reset_index()
    missing.columns = ["column", "missing_count"]
    missing["pct"] = (missing["missing_count"] / len(df) * 100).round(1)
    fig = px.bar(
        missing[missing["missing_count"] > 0],
        x="column",
        y="missing_count",
        title="Missing Values by Column",
        text="pct",
    )
    fig.update_traces(texttemplate="%{text}%", textposition="outside")
    st.plotly_chart(fig, use_container_width=True)

# ======================= TAB: Raw Data ====================================
with tab_data:
    st.subheader("Unified Dataset")

    # Filters
    has_spreadsheet = "spreadsheet_name" in df.columns
    n_filter_cols = 5 if has_spreadsheet else 4
    filter_cols = st.columns(n_filter_cols)
    filtered = df.copy()

    with filter_cols[0]:
        if "source" in df.columns:
            sources = ["All"] + sorted(df["source"].dropna().unique().tolist())
            sel_source = st.selectbox("Source", sources, key="raw_source")
            if sel_source != "All":
                filtered = filtered[filtered["source"] == sel_source]

    with filter_cols[1]:
        if "account_name" in df.columns:
            accounts = ["All"] + sorted(df["account_name"].dropna().unique().tolist())
            sel_account = st.selectbox("Ad Account", accounts, key="raw_account")
            if sel_account != "All":
                filtered = filtered[filtered["account_name"] == sel_account]

    with filter_cols[2]:
        if "campaign_name" in df.columns:
            campaigns = ["All"] + sorted(
                df["campaign_name"].dropna().unique().tolist()
            )
            sel_campaign = st.selectbox("Campaign", campaigns, key="raw_campaign")
            if sel_campaign != "All":
                filtered = filtered[filtered["campaign_name"] == sel_campaign]

    with filter_cols[3]:
        if "city" in df.columns:
            cities = ["All"] + sorted(df["city"].dropna().unique().tolist())
            sel_city = st.selectbox("City", cities, key="raw_city")
            if sel_city != "All":
                filtered = filtered[filtered["city"] == sel_city]

    if has_spreadsheet:
        with filter_cols[4]:
            sheets = ["All"] + sorted(
                df["spreadsheet_name"].dropna().unique().tolist()
            )
            sel_sheet = st.selectbox("Spreadsheet", sheets, key="raw_sheet")
            if sel_sheet != "All":
                filtered = filtered[filtered["spreadsheet_name"] == sel_sheet]

    st.dataframe(filtered, use_container_width=True)
    st.caption(f"Showing {len(filtered)} of {len(df)} rows")

    # Download
    csv = filtered.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download CSV",
        csv,
        "analytics_export.csv",
        "text/csv",
    )

    # Schema info
    with st.expander("Database tables"):
        tables = list_tables()
        st.write(tables)

# ---------------------------------------------------------------------------
# Footer — last sync time + auto-rerun scheduling
# ---------------------------------------------------------------------------
st.divider()
last_dt = st.session_state.get("last_sync_dt", "—")
st.caption(
    f"Last synced: {last_dt}  ·  "
    f"Auto-sync every {settings.sync_interval_minutes} min"
)

# Schedule next auto-rerun via st.rerun after the configured interval.
# st.rerun is only called when the timer expires; while the page is open
# Streamlit keeps a websocket alive and reruns will pick up fresh data.
if st.session_state.get("last_sync_time"):
    remaining = AUTO_SYNC_SECONDS - (time.time() - st.session_state["last_sync_time"])
    if remaining <= 0:
        st.rerun()
    else:
        # Use st.empty + time fragment to schedule next rerun
        _placeholder = st.empty()
        _placeholder.empty()
