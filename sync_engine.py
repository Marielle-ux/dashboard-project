"""
Data synchronization and correlation engine.

Merges Meta Ads campaign metrics with Google Sheets hospitality data
into a unified analytics dataset, correlating by date and city.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# City normalisation
# ---------------------------------------------------------------------------
_CITY_PATTERNS: dict[str, str] = {
    "актобе": "Актобе",
    "aktobe": "Актобе",
    "aqtobe": "Актобе",
    "атырау": "Атырау",
    "atyrau": "Атырау",
    "караганда": "Караганда",
    "karaganda": "Караганда",
    "астана": "Астана",
    "astana": "Астана",
}


def _extract_city(text: str) -> str:
    """Extract a normalised city name from free-text (account name, sheet title, etc.)."""
    lower = text.lower()
    for pattern, city in _CITY_PATTERNS.items():
        if pattern in lower:
            return city
    return text


# ---------------------------------------------------------------------------
# Source-specific aggregation
# ---------------------------------------------------------------------------
_META_NUMERIC = ["spend", "impressions", "clicks", "conversions"]


def prepare_meta_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate Meta Ads rows by date + city.

    Returns a DataFrame with columns:
        date, city, spend, impressions, clicks, conversions, ctr, cpc, cpm
    """
    if df.empty or "source" not in df.columns:
        return pd.DataFrame()

    meta = df[df["source"] == "meta_ads"].copy()
    if meta.empty:
        return pd.DataFrame()

    if "account_name" in meta.columns:
        meta["city"] = meta["account_name"].apply(_extract_city)
    elif "ad_account_id" in meta.columns:
        meta["city"] = meta["ad_account_id"].apply(_extract_city)
    else:
        meta["city"] = "Unknown"

    meta["date"] = pd.to_datetime(meta["date"], errors="coerce")

    for col in _META_NUMERIC:
        if col in meta.columns:
            meta[col] = pd.to_numeric(meta[col], errors="coerce").fillna(0)

    agg_cols = {c: "sum" for c in _META_NUMERIC if c in meta.columns}
    if "campaign_name" in meta.columns:
        agg_cols["campaign_name"] = "count"

    agg = meta.groupby(["date", "city"]).agg(agg_cols).reset_index()
    if "campaign_name" in agg.columns:
        agg = agg.rename(columns={"campaign_name": "campaigns_count"})

    imp = agg.get("impressions", pd.Series([0]))
    clk = agg.get("clicks", pd.Series([0]))
    spd = agg.get("spend", pd.Series([0]))
    agg["ctr"] = (clk / imp * 100).fillna(0).round(2)
    agg["cpc"] = (spd / clk).replace([float("inf"), float("-inf")], 0).fillna(0).round(2)
    agg["cpm"] = (spd / imp * 1000).replace([float("inf"), float("-inf")], 0).fillna(0).round(2)

    return agg


_REVENUE_COLS = ["revenue", "cabin_revenue", "hall_revenue"]
_GUEST_COLS = ["cabin_guests", "hall_guests"]


def prepare_sheets_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate Google Sheets hospitality rows by date + city.

    Returns a DataFrame with columns:
        date, city, revenue (+ component columns if present), total_guests
    """
    if df.empty or "source" not in df.columns:
        return pd.DataFrame()

    sheets = df[df["source"] == "google_sheets"].copy()
    if sheets.empty:
        return pd.DataFrame()

    if "spreadsheet_name" in sheets.columns:
        sheets["city"] = sheets["spreadsheet_name"].apply(_extract_city)
    else:
        sheets["city"] = "Unknown"

    sheets["date"] = pd.to_datetime(sheets["date"], errors="coerce")

    agg_dict: dict[str, str] = {}
    for col in _REVENUE_COLS + _GUEST_COLS:
        if col in sheets.columns:
            sheets[col] = pd.to_numeric(sheets[col], errors="coerce").fillna(0)
            agg_dict[col] = "sum"

    if not agg_dict:
        return pd.DataFrame()

    agg = sheets.groupby(["date", "city"]).agg(agg_dict).reset_index()

    if "cabin_revenue" in agg.columns and "hall_revenue" in agg.columns:
        if "revenue" not in agg.columns:
            agg["revenue"] = agg["cabin_revenue"] + agg["hall_revenue"]

    if "cabin_guests" in agg.columns and "hall_guests" in agg.columns:
        agg["total_guests"] = agg["cabin_guests"] + agg["hall_guests"]

    return agg


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------

def correlate_datasets(
    meta_summary: pd.DataFrame,
    sheets_summary: pd.DataFrame,
) -> pd.DataFrame:
    """Outer-join Meta Ads and Sheets summaries on (date, city).

    Prefixes non-key columns with ``meta_`` / ``sheets_`` and computes
    derived KPIs: ROAS, cost-per-guest.
    """
    if meta_summary.empty and sheets_summary.empty:
        return pd.DataFrame()
    if meta_summary.empty:
        return sheets_summary.copy()
    if sheets_summary.empty:
        return meta_summary.copy()

    meta_cols = {c: f"meta_{c}" for c in meta_summary.columns if c not in ("date", "city")}
    sheets_cols = {c: f"sheets_{c}" for c in sheets_summary.columns if c not in ("date", "city")}

    correlated = pd.merge(
        meta_summary.rename(columns=meta_cols),
        sheets_summary.rename(columns=sheets_cols),
        on=["date", "city"],
        how="outer",
    )

    if "meta_spend" in correlated.columns and "sheets_revenue" in correlated.columns:
        correlated["roas"] = (
            correlated["sheets_revenue"] / correlated["meta_spend"]
        ).replace([float("inf"), float("-inf")], 0).fillna(0).round(2)

    if "meta_spend" in correlated.columns and "sheets_total_guests" in correlated.columns:
        correlated["cost_per_guest"] = (
            correlated["meta_spend"] / correlated["sheets_total_guests"]
        ).replace([float("inf"), float("-inf")], 0).fillna(0).round(2)

    return correlated.sort_values(["date", "city"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Top-level builder
# ---------------------------------------------------------------------------

def build_unified_analytics(all_data: pd.DataFrame) -> dict:
    """Build the full analytics context from the unified dataset.

    Returns
    -------
    dict with keys:
        meta_summary, sheets_summary, correlated, overview_kpis
    """
    meta_summary = prepare_meta_summary(all_data)
    sheets_summary = prepare_sheets_summary(all_data)
    correlated = correlate_datasets(meta_summary, sheets_summary)

    kpis: dict = {}

    if not meta_summary.empty:
        kpis["total_spend"] = meta_summary["spend"].sum()
        kpis["total_impressions"] = int(meta_summary["impressions"].sum())
        kpis["total_clicks"] = int(meta_summary["clicks"].sum())
        kpis["total_conversions"] = int(meta_summary.get("conversions", pd.Series([0])).sum())
        imp = kpis["total_impressions"]
        clk = kpis["total_clicks"]
        spd = kpis["total_spend"]
        kpis["avg_ctr"] = round(clk / imp * 100, 2) if imp else 0
        kpis["avg_cpc"] = round(spd / clk, 2) if clk else 0
        kpis["avg_cpm"] = round(spd / imp * 1000, 2) if imp else 0

    if not sheets_summary.empty:
        kpis["total_revenue"] = sheets_summary.get("revenue", pd.Series([0])).sum()
        if "total_guests" in sheets_summary.columns:
            kpis["total_guests"] = int(sheets_summary["total_guests"].sum())

    if kpis.get("total_spend") and kpis.get("total_revenue"):
        kpis["overall_roas"] = round(kpis["total_revenue"] / kpis["total_spend"], 2)

    return {
        "meta_summary": meta_summary,
        "sheets_summary": sheets_summary,
        "correlated": correlated,
        "overview_kpis": kpis,
    }
