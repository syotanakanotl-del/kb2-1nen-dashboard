from __future__ import annotations

import pandas as pd
import streamlit as st

from lib.bq import load_subscription_master

st.set_page_config(page_title="詳細データ", page_icon="🔍", layout="wide")
st.title("詳細データ")
st.caption("subscription_master_KB2_1nen をフィルタ・検索")

df = load_subscription_master()

if df.empty:
    st.info("データがありません。")
    st.stop()

df = df.copy()
df["成約日"] = pd.to_datetime(df["成約日"])

with st.sidebar:
    st.header("フィルタ")

    min_date = df["成約日"].min().date()
    max_date = df["成約日"].max().date()
    date_range = st.date_input(
        "成約日 範囲",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )

    companies = sorted(df["企業名"].dropna().unique().tolist())
    sel_company = st.multiselect("企業名", companies)

    ops = sorted(df["担当者名"].dropna().unique().tolist())
    sel_op = st.multiselect("担当者名", ops)

    coupons = sorted(df["クーポン"].dropna().unique().tolist())
    sel_coupon = st.multiselect("クーポン", coupons)

    sources = sorted(df["source_tab"].dropna().unique().tolist())
    sel_source = st.multiselect("source_tab", sources)

filtered = df.copy()
if isinstance(date_range, tuple) and len(date_range) == 2:
    start, end = date_range
    filtered = filtered[(filtered["成約日"].dt.date >= start) & (filtered["成約日"].dt.date <= end)]
if sel_company:
    filtered = filtered[filtered["企業名"].isin(sel_company)]
if sel_op:
    filtered = filtered[filtered["担当者名"].isin(sel_op)]
if sel_coupon:
    filtered = filtered[filtered["クーポン"].isin(sel_coupon)]
if sel_source:
    filtered = filtered[filtered["source_tab"].isin(sel_source)]

c1, c2, c3 = st.columns(3)
c1.metric("件数", f"{len(filtered):,}")
c2.metric("企業数", f"{filtered['企業名'].nunique():,}")
c3.metric("担当者数", f"{filtered['担当者名'].nunique():,}")

st.dataframe(
    filtered.sort_values("成約日", ascending=False),
    use_container_width=True,
    hide_index=True,
    column_config={
        "成約日": st.column_config.DateColumn(format="YYYY-MM-DD"),
        "マスタID": st.column_config.NumberColumn(format="%d"),
    },
)

st.download_button(
    "CSVダウンロード",
    filtered.to_csv(index=False).encode("utf-8-sig"),
    file_name="subscription_master_filtered.csv",
    mime="text/csv",
)
