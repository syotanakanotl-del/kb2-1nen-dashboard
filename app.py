from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from lib.bq import (
    load_monthly_shipments,
    load_monthly_subscriptions,
    load_op_receive_rate,
    recent_month_labels,
)

st.set_page_config(
    page_title="KB2 1年定期ダッシュボード",
    page_icon="📊",
    layout="wide",
)

st.title("KB2 1年定期ダッシュボード")
st.caption("trustline-project.KB2_1nen / 業務レポート")

with st.sidebar:
    st.header("メニュー")
    st.write("- **サマリー** (このページ)")
    st.write("- **OP別パフォーマンス**")
    st.write("- **OP別月間受取率**")
    st.write("- **OP別デイリー受取率**")
    st.write("- **継続率**")
    st.write("- **詳細データ**")
    st.divider()
    if st.button("キャッシュをクリア", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

labels = recent_month_labels()
M_THIS = labels["this"]     # e.g. "5月"
M_PREV = labels["prev"]     # e.g. "4月"
M_PREV2 = labels["prev2"]   # e.g. "3月"

op_df = load_op_receive_rate()

agg = {
    f"{M_THIS}_成約数": int(op_df[f"{M_THIS}_成約数"].fillna(0).sum()),
    f"{M_THIS}_初回受取数": int(op_df[f"{M_THIS}_初回受取数"].fillna(0).sum()),
    f"{M_PREV}_成約数": int(op_df[f"{M_PREV}_成約数"].fillna(0).sum()),
    f"{M_PREV}_初回受取数": int(op_df[f"{M_PREV}_初回受取数"].fillna(0).sum()),
    f"{M_PREV2}_成約数": int(op_df[f"{M_PREV2}_成約数"].fillna(0).sum()),
    f"{M_PREV2}_初回受取数": int(op_df[f"{M_PREV2}_初回受取数"].fillna(0).sum()),
}


def safe_rate(num: int, den: int) -> float | None:
    return num / den if den else None


cur_rate = safe_rate(agg[f"{M_THIS}_初回受取数"], agg[f"{M_THIS}_成約数"])
prev_rate = safe_rate(agg[f"{M_PREV}_初回受取数"], agg[f"{M_PREV}_成約数"])
prev2_rate = safe_rate(agg[f"{M_PREV2}_初回受取数"], agg[f"{M_PREV2}_成約数"])


def fmt_pct(v: float | None) -> str:
    return f"{v:.1%}" if v is not None else "—"


def delta_pct(cur: float | None, prev: float | None) -> str | None:
    if cur is None or prev is None:
        return None
    return f"{(cur - prev) * 100:+.1f}pt"


st.subheader("初回受取率（主要KPI）")
st.caption("成約のうち、発送（対応状況=5）が21日以上前に1件以上ある割合。"
           f"**{M_PREV} 以前が評価可能**な数値です。")
c1, c2, c3 = st.columns(3)
c1.metric(
    f"{M_PREV} 初回受取率（評価可）",
    fmt_pct(prev_rate),
    delta_pct(prev_rate, prev2_rate),
    help=f"{agg[f'{M_PREV}_初回受取数']:,} / {agg[f'{M_PREV}_成約数']:,} 件",
)
c2.metric(
    f"{M_PREV2} 初回受取率",
    fmt_pct(prev2_rate),
    help=f"{agg[f'{M_PREV2}_初回受取数']:,} / {agg[f'{M_PREV2}_成約数']:,} 件",
)
c3.metric(
    f"{M_THIS} 初回受取率（21日未経過のため低めに出ます）",
    fmt_pct(cur_rate),
    help=f"{agg[f'{M_THIS}_初回受取数']:,} / {agg[f'{M_THIS}_成約数']:,} 件",
)

st.divider()

st.subheader("成約数・初回受取数（全体）")
c1, c2, c3, c4 = st.columns(4)
c1.metric(
    f"{M_THIS} 成約数",
    f"{agg[f'{M_THIS}_成約数']:,}",
    f"{agg[f'{M_THIS}_成約数'] - agg[f'{M_PREV}_成約数']:+,} vs {M_PREV}",
)
c2.metric(
    f"{M_PREV} 成約数",
    f"{agg[f'{M_PREV}_成約数']:,}",
    f"{agg[f'{M_PREV}_成約数'] - agg[f'{M_PREV2}_成約数']:+,} vs {M_PREV2}",
)
c3.metric(
    f"{M_PREV} 初回受取数",
    f"{agg[f'{M_PREV}_初回受取数']:,}",
    f"{agg[f'{M_PREV}_初回受取数'] - agg[f'{M_PREV2}_初回受取数']:+,} vs {M_PREV2}",
)
c4.metric(f"{M_PREV2} 初回受取数", f"{agg[f'{M_PREV2}_初回受取数']:,}")

st.divider()

st.subheader("月別 成約数 / 発送数")
subs_df = load_monthly_subscriptions()
ship_df = load_monthly_shipments()

if not subs_df.empty or not ship_df.empty:
    merged = pd.merge(
        subs_df.rename(columns={"subscriptions": "成約数"}),
        ship_df.rename(columns={"shipments": "発送数"}),
        on="month",
        how="outer",
    ).sort_values("month")
    merged["month"] = pd.to_datetime(merged["month"])
    long = merged.melt(id_vars="month", value_vars=["成約数", "発送数"], var_name="種別", value_name="件数")
    fig = px.line(long, x="month", y="件数", color="種別", markers=True)
    fig.update_layout(xaxis_title="月", yaxis_title="件数", legend_title=None)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("データがありません。")

st.divider()

st.subheader("3ヶ月比較（全OP合計）")
cmp_df = pd.DataFrame(
    {
        "月": [M_PREV2, M_PREV, M_THIS],
        "成約数": [agg[f"{M_PREV2}_成約数"], agg[f"{M_PREV}_成約数"], agg[f"{M_THIS}_成約数"]],
        "初回受取数": [agg[f"{M_PREV2}_初回受取数"], agg[f"{M_PREV}_初回受取数"], agg[f"{M_THIS}_初回受取数"]],
        "初回受取率": [prev2_rate or 0, prev_rate or 0, cur_rate or 0],
    }
)
col_a, col_b = st.columns(2)
with col_a:
    long_cnt = cmp_df.melt(id_vars="月", value_vars=["成約数", "初回受取数"], var_name="指標", value_name="件数")
    fig = px.bar(long_cnt, x="月", y="件数", color="指標", barmode="group", text_auto=True)
    fig.update_layout(xaxis_title=None)
    st.plotly_chart(fig, use_container_width=True)
with col_b:
    fig = px.bar(
        cmp_df,
        x="月",
        y="初回受取率",
        text=cmp_df["初回受取率"].map(lambda v: f"{v:.1%}"),
        color="初回受取率",
        color_continuous_scale="RdYlGn",
        range_color=[0, 1],
    )
    fig.update_layout(xaxis_title=None, yaxis_tickformat=".0%", coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)
