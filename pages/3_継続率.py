from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from lib.bq import load_retention

st.set_page_config(page_title="継続率", page_icon="📈", layout="wide")
st.title("継続率（コホート分析）")
st.caption("成約月別のステップ間継続率と累積継続率")

df = load_retention()

if df.empty:
    st.info("データがありません。")
    st.stop()

with st.sidebar:
    st.header("フィルタ")
    months = df["first_purchase_month"].dropna().tolist()
    sel_months = st.multiselect("成約月", months, default=months)

filtered = df[df["first_purchase_month"].isin(sel_months)].copy()

rate_cols = [c for c in df.columns if c.startswith("rate_")]
cnt_cols = [c for c in df.columns if c.startswith("cnt_")]


def step_num(col: str) -> int:
    return int(col.split("_")[1])


rate_cols.sort(key=step_num)
cnt_cols.sort(key=step_num)

st.subheader("ステップ間継続率 (ヒートマップ)")
heat = filtered.set_index("first_purchase_month")[rate_cols].copy()
heat.columns = [f"{step_num(c)}回目" for c in heat.columns]
fig = px.imshow(
    heat,
    color_continuous_scale="RdYlGn",
    aspect="auto",
    zmin=0,
    zmax=1,
    text_auto=".0%",
)
fig.update_layout(xaxis_title="ステップ", yaxis_title="成約月", coloraxis_colorbar_tickformat=".0%")
st.plotly_chart(fig, use_container_width=True)

st.divider()

st.subheader("累積継続率 (1回目を100%とした到達率)")
cum_records = []
for _, row in filtered.iterrows():
    month = row["first_purchase_month"]
    total = row["total_subscriptions"] or 0
    if total == 0:
        continue
    for col in cnt_cols:
        n = step_num(col)
        cnt = row[col]
        if pd.isna(cnt):
            continue
        cum_records.append(
            {
                "first_purchase_month": month,
                "step": n,
                "cum_rate": (cnt or 0) / total,
            }
        )
cum_df = pd.DataFrame(cum_records)
if not cum_df.empty:
    fig = px.line(
        cum_df,
        x="step",
        y="cum_rate",
        color="first_purchase_month",
        markers=True,
    )
    fig.update_layout(xaxis_title="N回目", yaxis_title="累積継続率", yaxis_tickformat=".0%", yaxis_range=[0, 1])
    st.plotly_chart(fig, use_container_width=True)

st.divider()

st.subheader("生データ")
fmt = {c: "{:.1%}" for c in rate_cols}
fmt["total_subscriptions"] = "{:,.0f}"
for c in cnt_cols:
    fmt[c] = "{:,.0f}"
st.dataframe(
    filtered.style.format(fmt, na_rep="—").background_gradient(
        subset=rate_cols, cmap="RdYlGn", vmin=0, vmax=1
    ),
    use_container_width=True,
    hide_index=True,
)
