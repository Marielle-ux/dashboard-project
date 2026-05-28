"""
Modular Streamlit dashboard view components.

Each ``render_*`` function draws one section of the UI using data
prepared by :mod:`sync_engine`.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st


# ===================== A) Overview KPIs ====================================

def render_overview_kpis(kpis: dict) -> None:
    """Display top-level KPI cards (spend, impressions, clicks, CTR, CPC)."""
    st.subheader("Overview KPIs")

    row1 = st.columns(5)
    with row1[0]:
        st.metric("Total Spend", f"{kpis.get('total_spend', 0):,.2f}")
    with row1[1]:
        st.metric("Total Impressions", f"{kpis.get('total_impressions', 0):,}")
    with row1[2]:
        st.metric("Total Clicks", f"{kpis.get('total_clicks', 0):,}")
    with row1[3]:
        st.metric("Avg CTR", f"{kpis.get('avg_ctr', 0):.2f}%")
    with row1[4]:
        st.metric("Avg CPC", f"{kpis.get('avg_cpc', 0):.2f}")

    has_extra = any(kpis.get(k) for k in ("total_revenue", "total_guests", "overall_roas"))
    row2 = st.columns(4)
    with row2[0]:
        st.metric("Total Conversions", f"{kpis.get('total_conversions', 0):,}")
    with row2[1]:
        val = kpis.get("total_revenue", 0)
        st.metric("Total Revenue", f"{val:,.0f}" if val else "—")
    with row2[2]:
        val = kpis.get("total_guests", 0)
        st.metric("Total Guests", f"{val:,}" if val else "—")
    with row2[3]:
        val = kpis.get("overall_roas", 0)
        st.metric("ROAS", f"{val:.2f}x" if val else "—")


# ===================== B) Campaign Comparison Table ========================

def render_campaign_comparison(correlated: pd.DataFrame) -> None:
    """Display the merged Meta Ads + Sheets comparison table with filters."""
    st.subheader("Campaign Comparison — Meta Ads + Sheets")

    if correlated.empty:
        st.info("No correlated data available. Ensure both Meta Ads and Google Sheets data are loaded.")
        return

    cities = sorted(correlated["city"].dropna().unique()) if "city" in correlated.columns else []
    if cities:
        selected = st.multiselect("Filter by city", cities, default=cities, key="comp_city")
        display = correlated[correlated["city"].isin(selected)]
    else:
        display = correlated

    rename_map = {}
    for col in display.columns:
        clean = col.replace("meta_", "Meta: ").replace("sheets_", "Sheets: ")
        if clean != col:
            rename_map[col] = clean
    styled = display.rename(columns=rename_map)

    st.dataframe(styled, use_container_width=True, hide_index=True)

    csv = display.to_csv(index=False).encode("utf-8")
    st.download_button("Download comparison CSV", csv, "comparison.csv", "text/csv")


# ===================== C) Time Series Charts ===============================

def render_time_series(meta_summary: pd.DataFrame) -> None:
    """Render spend-over-time and clicks-over-time line charts."""
    st.subheader("Time Series")

    if meta_summary.empty:
        st.info("No Meta Ads time-series data available.")
        return

    daily = meta_summary.copy()
    daily["date"] = pd.to_datetime(daily["date"])

    col1, col2 = st.columns(2)
    with col1:
        agg = daily.groupby("date")["spend"].sum().reset_index()
        fig = px.line(agg, x="date", y="spend", title="Daily Spend")
        fig.update_layout(xaxis_title="Date", yaxis_title="Spend")
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        agg = daily.groupby("date")["clicks"].sum().reset_index()
        fig = px.line(agg, x="date", y="clicks", title="Daily Clicks")
        fig.update_layout(xaxis_title="Date", yaxis_title="Clicks")
        st.plotly_chart(fig, use_container_width=True)

    if "city" in daily.columns and daily["city"].nunique() > 1:
        col3, col4 = st.columns(2)
        with col3:
            fig = px.line(daily, x="date", y="spend", color="city", title="Spend by City")
            st.plotly_chart(fig, use_container_width=True)
        with col4:
            fig = px.line(daily, x="date", y="clicks", color="city", title="Clicks by City")
            st.plotly_chart(fig, use_container_width=True)


# ===================== D) Correlation View =================================

def render_correlation_view(correlated: pd.DataFrame) -> None:
    """Show differences between Meta Ads and Google Sheets tracking data."""
    st.subheader("Correlation — Meta Ads vs Google Sheets")

    if correlated.empty or "meta_spend" not in correlated.columns:
        st.info(
            "Correlation requires both Meta Ads and Google Sheets data "
            "loaded for the same cities / dates."
        )
        return

    has_revenue = "sheets_revenue" in correlated.columns
    has_guests = "sheets_total_guests" in correlated.columns

    if not has_revenue and not has_guests:
        st.info("No Google Sheets revenue / guest data to correlate with Meta Ads.")
        return

    # ------- ROAS by city -------
    if has_revenue and "roas" in correlated.columns:
        by_city = correlated.groupby("city").agg(
            meta_spend=("meta_spend", "sum"),
            sheets_revenue=("sheets_revenue", "sum"),
        ).reset_index()
        by_city["ROAS"] = (by_city["sheets_revenue"] / by_city["meta_spend"]).round(2)

        c1, c2 = st.columns(2)
        with c1:
            fig = px.bar(
                by_city, x="city",
                y=["meta_spend", "sheets_revenue"],
                barmode="group",
                title="Ad Spend vs Revenue by City",
                labels={"value": "Amount", "variable": "Metric"},
            )
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = px.bar(
                by_city, x="city", y="ROAS",
                title="Return on Ad Spend (ROAS) by City",
                text="ROAS",
            )
            st.plotly_chart(fig, use_container_width=True)

    # ------- Daily spend vs revenue overlay -------
    if has_revenue:
        daily = correlated.groupby("date").agg(
            meta_spend=("meta_spend", "sum"),
            sheets_revenue=("sheets_revenue", "sum"),
        ).reset_index()
        daily["date"] = pd.to_datetime(daily["date"])

        fig = px.line(
            daily.melt(id_vars="date", value_vars=["meta_spend", "sheets_revenue"]),
            x="date", y="value", color="variable",
            title="Daily Spend vs Revenue",
            labels={"value": "Amount", "variable": "Source"},
        )
        st.plotly_chart(fig, use_container_width=True)

    # ------- Cost per guest -------
    if has_guests and "cost_per_guest" in correlated.columns:
        by_city = correlated.groupby("city").agg(
            meta_spend=("meta_spend", "sum"),
            sheets_total_guests=("sheets_total_guests", "sum"),
        ).reset_index()
        by_city["Cost per Guest"] = (
            by_city["meta_spend"] / by_city["sheets_total_guests"]
        ).replace([float("inf"), float("-inf")], 0).round(2)

        fig = px.bar(
            by_city, x="city", y="Cost per Guest",
            title="Cost per Guest by City",
            text="Cost per Guest",
        )
        st.plotly_chart(fig, use_container_width=True)
