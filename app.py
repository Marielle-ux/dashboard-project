"""
Marketing Analytics Dashboard
Unified view of Meta Ads + Google Sheets / Excel reports.
"""

import logging
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import settings
from db.database import list_tables, load_dataframe
from etl.excel_loader import load_uploaded_file
from etl.google_sheets import load_sheet
from etl.normalizer import (
    coerce_numeric_columns,
    normalize_columns,
    standardize_date_column,
)
from etl.cleaner import clean_dataframe
from etl.merger import concat_datasets, merge_datasets
from etl.meta_ads import fetch_campaign_insights
from etl.pipeline import load_cached_data, run_pipeline

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
        "Set META_ACCESS_TOKEN and META_AD_ACCOUNT_ID in .env to enable."
    )

# Google Sheets
use_gsheets = st.sidebar.checkbox(
    "Load Google Sheets",
    value=False,
)
gsheet_name = ""
gsheet_worksheet = ""
if use_gsheets:
    gsheet_name = st.sidebar.text_input("Spreadsheet name")
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


# Gather all sources
all_dfs: list[pd.DataFrame] = []

if run_sync or "unified_data" not in st.session_state:
    with st.spinner("Loading data ..."):
        # Meta Ads
        if use_meta and settings.meta_ads.is_configured:
            meta_df = fetch_meta(start_date, end_date)
            if not meta_df.empty:
                all_dfs.append(meta_df)

        # Google Sheets
        if use_gsheets and gsheet_name:
            gs_df = fetch_gsheet(gsheet_name, gsheet_worksheet)
            if not gs_df.empty:
                gs_df = normalize_columns(gs_df)
                gs_df = standardize_date_column(gs_df)
                gs_df = coerce_numeric_columns(gs_df)
                if "source" not in gs_df.columns:
                    gs_df["source"] = "google_sheets"
                all_dfs.append(gs_df)

        # Uploaded files
        for uf in uploaded_files:
            udf = load_uploaded_file(uf)
            if not udf.empty:
                udf = normalize_columns(udf)
                udf = standardize_date_column(udf)
                udf = coerce_numeric_columns(udf)
                if "source" not in udf.columns:
                    udf["source"] = f"upload:{uf.name}"
                all_dfs.append(udf)

        # Existing city tables
        if use_city_data:
            for city in city_selection:
                cdf = load_city_table(city)
                if not cdf.empty:
                    all_dfs.append(cdf)

        # Merge
        if all_dfs:
            unified = concat_datasets(all_dfs)
            unified = clean_dataframe(unified)
        else:
            unified = load_cached_data()

        st.session_state["unified_data"] = unified

df = st.session_state.get("unified_data", pd.DataFrame())

# ---------------------------------------------------------------------------
# Connection status
# ---------------------------------------------------------------------------
col1, col2, col3 = st.columns(3)
with col1:
    status = "Connected" if settings.meta_ads.is_configured else "Not configured"
    st.metric("Meta Ads API", status)
with col2:
    status = "Connected" if settings.google_sheets.is_configured else "Not configured"
    st.metric("Google Sheets", status)
with col3:
    st.metric("Total rows loaded", len(df))

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
tab_overview, tab_meta, tab_reports, tab_data = st.tabs(
    ["Overview", "Meta Ads Metrics", "Reports", "Raw Data"]
)

# ---- Helpers ----
METRIC_COLS = ["spend", "impressions", "cpm", "cpc", "ctr", "clicks", "conversions"]
available_metrics = [m for m in METRIC_COLS if m in df.columns]


def safe_sum(series: pd.Series) -> float:
    return pd.to_numeric(series, errors="coerce").sum()


# ======================= TAB: Overview ====================================
with tab_overview:
    st.subheader("Key Metrics Summary")

    kpi_cols = st.columns(len(available_metrics) if available_metrics else 1)
    for i, metric in enumerate(available_metrics):
        with kpi_cols[i]:
            val = safe_sum(df[metric])
            fmt = f"{val:,.2f}" if metric in ("spend", "cpm", "cpc", "ctr") else f"{int(val):,}"
            st.metric(metric.upper(), fmt)

    # Time series
    if "date" in df.columns and available_metrics:
        st.subheader("Metrics Over Time")
        chosen_metric = st.selectbox(
            "Select metric", available_metrics, key="overview_metric"
        )
        ts = df.copy()
        ts["date"] = pd.to_datetime(ts["date"], errors="coerce")
        ts = ts.dropna(subset=["date"])
        if not ts.empty:
            daily = (
                ts.groupby("date")[chosen_metric]
                .apply(lambda s: pd.to_numeric(s, errors="coerce").sum())
                .reset_index()
            )
            fig = px.line(
                daily,
                x="date",
                y=chosen_metric,
                title=f"Daily {chosen_metric.upper()}",
            )
            st.plotly_chart(fig, use_container_width=True)

    # By source
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
        # Campaign breakdown
        if "campaign_name" in meta_data.columns:
            st.markdown("#### Campaign Breakdown")
            campaign_metrics = (
                meta_data.groupby("campaign_name")[available_metrics]
                .apply(lambda g: g.apply(pd.to_numeric, errors="coerce").sum())
                .reset_index()
            )
            st.dataframe(campaign_metrics, use_container_width=True)

            # Spend by campaign
            if "spend" in available_metrics:
                fig = px.pie(
                    campaign_metrics,
                    names="campaign_name",
                    values="spend",
                    title="Spend Distribution by Campaign",
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
    filter_cols = st.columns(3)
    filtered = df.copy()

    with filter_cols[0]:
        if "source" in df.columns:
            sources = ["All"] + sorted(df["source"].dropna().unique().tolist())
            sel_source = st.selectbox("Source", sources, key="raw_source")
            if sel_source != "All":
                filtered = filtered[filtered["source"] == sel_source]

    with filter_cols[1]:
        if "campaign_name" in df.columns:
            campaigns = ["All"] + sorted(
                df["campaign_name"].dropna().unique().tolist()
            )
            sel_campaign = st.selectbox("Campaign", campaigns, key="raw_campaign")
            if sel_campaign != "All":
                filtered = filtered[filtered["campaign_name"] == sel_campaign]

    with filter_cols[2]:
        if "city" in df.columns:
            cities = ["All"] + sorted(df["city"].dropna().unique().tolist())
            sel_city = st.selectbox("City", cities, key="raw_city")
            if sel_city != "All":
                filtered = filtered[filtered["city"] == sel_city]

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
