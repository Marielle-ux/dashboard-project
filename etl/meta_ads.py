"""
Meta (Facebook) Ads Manager API integration.
Fetches campaign-level metrics via the Marketing API.
Supports multiple ad accounts.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
import requests

from config import settings

logger = logging.getLogger(__name__)

API_BASE = "https://graph.facebook.com"

FIELDS = [
    "campaign_name",
    "adset_name",
    "ad_name",
    "spend",
    "impressions",
    "cpm",
    "cpc",
    "ctr",
    "clicks",
    "actions",
    "date_start",
    "date_stop",
]

META_DF_COLUMNS = [
    "date",
    "campaign_name",
    "ad_set",
    "spend",
    "impressions",
    "cpm",
    "cpc",
    "ctr",
    "clicks",
    "conversions",
    "ad_account_id",
    "account_name",
    "source",
]


def _build_url(endpoint: str) -> str:
    cfg = settings.meta_ads
    return f"{API_BASE}/{cfg.api_version}/{endpoint}"


def _default_params() -> dict:
    return {"access_token": settings.meta_ads.access_token}


def _normalize_account_id(raw: str) -> str:
    """Ensure account ID has the ``act_`` prefix."""
    raw = raw.strip()
    if not raw.startswith("act_"):
        return f"act_{raw}"
    return raw


def _parse_conversions(actions: list[dict] | None) -> int:
    """Extract total conversions from the actions breakdown."""
    if not actions:
        return 0
    conversion_types = {
        "offsite_conversion",
        "lead",
        "complete_registration",
        "purchase",
        "add_to_cart",
        "initiate_checkout",
        "onsite_conversion.messaging_first_reply",
        "onsite_conversion.messaging_conversation_started_7d",
        "onsite_conversion.total_messaging_connection",
    }
    total = 0
    for action in actions:
        action_type = action.get("action_type", "")
        if action_type in conversion_types or any(
            ct in action_type for ct in {"offsite_conversion", "lead", "purchase"}
        ):
            total += int(action.get("value", 0))
    return total


# ---------------------------------------------------------------------------
# Per-account helpers
# ---------------------------------------------------------------------------

def check_account_status(account_id: str) -> tuple[str, str]:
    """Validate a single ad account. Returns (status, detail)."""
    cfg = settings.meta_ads
    aid = _normalize_account_id(account_id)
    try:
        r = requests.get(
            f"{API_BASE}/{cfg.api_version}/{aid}",
            params={"access_token": cfg.access_token, "fields": "name,account_status"},
            timeout=15,
        )
        data = r.json()
        if "error" in data:
            err = data["error"]
            code = err.get("code", 0)
            msg = err.get("message", "")
            if code == 190:
                return "Token invalid", msg
            if code in (10, 200):
                return "Permission denied", msg
            if code == 100:
                return "No access", msg
            return "API error", msg
        return "Connected", data.get("name", aid)
    except requests.RequestException as exc:
        return "Connection error", str(exc)


def _fetch_single_account(
    account_id: str,
    start_date: date,
    end_date: date,
    level: str,
) -> pd.DataFrame:
    """Fetch insights for one ad account. Returns empty DF on failure."""
    aid = _normalize_account_id(account_id)
    url = _build_url(f"{aid}/insights")
    params = {
        **_default_params(),
        "fields": ",".join(FIELDS),
        "time_range": f'{{"since":"{start_date}","until":"{end_date}"}}',
        "level": level,
        "time_increment": 1,
        "limit": 500,
    }

    all_rows: list[dict] = []
    try:
        while url:
            resp = requests.get(url, params=params, timeout=60)
            payload = resp.json()
            if "error" in payload:
                err = payload["error"]
                logger.error(
                    "Meta Ads API error for %s (code=%s): %s",
                    aid, err.get("code"), err.get("message"),
                )
                return _empty_meta_df()
            resp.raise_for_status()
            all_rows.extend(payload.get("data", []))
            paging = payload.get("paging", {})
            url = paging.get("next")
            params = {}
    except requests.RequestException as exc:
        logger.error("Meta Ads API request failed for %s: %s", aid, exc)
        return _empty_meta_df()

    if not all_rows:
        logger.info("No data returned from Meta Ads API for %s", aid)
        return _empty_meta_df()

    logger.info("Fetched %d rows from %s", len(all_rows), aid)
    df = pd.DataFrame(all_rows)
    result = _transform_insights(df)

    status, account_name = check_account_status(account_id)
    result["ad_account_id"] = aid
    result["account_name"] = account_name if status == "Connected" else aid

    return result


def fetch_campaign_insights(
    start_date: date | None = None,
    end_date: date | None = None,
    level: str = "campaign",
) -> pd.DataFrame:
    """
    Fetch ad insights from Meta Ads API across all configured accounts.

    Returns
    -------
    pd.DataFrame with columns:
        date, campaign_name, ad_set, spend, impressions,
        cpm, cpc, ctr, clicks, conversions,
        ad_account_id, account_name, source
    """
    cfg = settings.meta_ads
    if not cfg.is_configured:
        logger.warning("Meta Ads API is not configured – returning empty DataFrame")
        return _empty_meta_df()

    if start_date is None:
        start_date = date.today() - timedelta(days=30)
    if end_date is None:
        end_date = date.today()

    account_dfs: list[pd.DataFrame] = []
    for account_id in cfg.ad_account_ids:
        logger.info("Fetching data for account %s ...", account_id)
        adf = _fetch_single_account(account_id, start_date, end_date, level)
        if not adf.empty:
            account_dfs.append(adf)

    if not account_dfs:
        logger.info("No data returned from any Meta Ads account")
        return _empty_meta_df()

    combined = pd.concat(account_dfs, ignore_index=True)
    logger.info(
        "Fetched %d total rows from %d account(s)",
        len(combined), len(account_dfs),
    )
    return combined


def _transform_insights(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw API response into a clean DataFrame."""
    result = pd.DataFrame()
    result["date"] = pd.to_datetime(df["date_start"]).dt.date
    result["campaign_name"] = df.get("campaign_name", "")
    result["ad_set"] = df.get("adset_name", "")
    result["spend"] = pd.to_numeric(df.get("spend", 0), errors="coerce").fillna(0)
    result["impressions"] = pd.to_numeric(
        df.get("impressions", 0), errors="coerce"
    ).fillna(0).astype(int)
    result["cpm"] = pd.to_numeric(df.get("cpm", 0), errors="coerce").fillna(0)
    result["cpc"] = pd.to_numeric(df.get("cpc", 0), errors="coerce").fillna(0)
    result["ctr"] = pd.to_numeric(df.get("ctr", 0), errors="coerce").fillna(0)
    result["clicks"] = pd.to_numeric(
        df.get("clicks", 0), errors="coerce"
    ).fillna(0).astype(int)
    result["conversions"] = df.get("actions", pd.Series([None] * len(df))).apply(
        _parse_conversions
    )
    result["source"] = "meta_ads"
    return result


def _empty_meta_df() -> pd.DataFrame:
    return pd.DataFrame(columns=META_DF_COLUMNS)
