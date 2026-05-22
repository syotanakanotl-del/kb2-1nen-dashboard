from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from lib.bq import load_op_receive_rate, recent_month_labels

st.set_page_config(page_title="OP別パフォーマンス", page_icon="👥", layout="wide")
st.title("OP別パフォーマンス")

labels = recent_month_labels()
M_THIS = labels["this"]
M_PREV = labels["prev"]
M_PREV2 = labels["prev2"]

st.caption(
    "**初回受取率** ＝ 成約のうち、発送完了（対応状況=5）が"
    "21日以上前に1件以上あった割合。"
    f"{M_THIS}の成約は21日未経過のため低めに出るのが正常です。"
    f"**{M_PREV}以前の数値を主な評価指標として** ご覧ください。"
)

df = load_op_receive_rate()

if df.empty:
    st.info("データがありません。")
    st.stop()

with st.sidebar:
    st.header("フィルタ")
    op_names = sorted(df["OP名"].dropna().unique().tolist())
    selected = st.multiselect("OP名", op_names, default=op_names)
    sort_target = st.selectbox(
        "並び替え基準",
        [
            f"{M_PREV}_初回受取率",
            f"{M_PREV2}_初回受取率",
            f"{M_THIS}_初回受取率",
            f"{M_PREV}_成約数",
            "OP名",
        ],
        index=0,
        help=f"既定は {M_PREV}_初回受取率（評価しやすい指標）",
    )

filtered = df[df["OP名"].isin(selected)] if selected else df


def overall_rate(month_label: str) -> tuple[int, int, float | None]:
    seiyaku = int(filtered[f"{month_label}_成約数"].fillna(0).sum())
    uketori = int(filtered[f"{month_label}_初回受取数"].fillna(0).sum())
    rate = uketori / seiyaku if seiyaku else None
    return seiyaku, uketori, rate


pm_s, pm_u, pm_r = overall_rate(M_PREV)
pm2_s, pm2_u, pm2_r = overall_rate(M_PREV2)
cm_s, cm_u, cm_r = overall_rate(M_THIS)


def fmt_pct(v: float | None) -> str:
    return f"{v:.1%}" if v is not None else "—"


def delta_pt(cur: float | None, base: float | None) -> str | None:
    if cur is None or base is None:
        return None
    return f"{(cur - base) * 100:+.1f}pt"


st.subheader("初回受取率（全体）")
c1, c2, c3 = st.columns(3)
c1.metric(
    f"{M_PREV}（評価可）",
    fmt_pct(pm_r),
    delta_pt(pm_r, pm2_r),
    help=f"{pm_u:,} / {pm_s:,} 件",
)
c2.metric(
    f"{M_PREV2}",
    fmt_pct(pm2_r),
    help=f"{pm2_u:,} / {pm2_s:,} 件",
)
c3.metric(
    f"{M_THIS}（21日未経過なので低めに出ます）",
    fmt_pct(cm_r),
    help=f"{cm_u:,} / {cm_s:,} 件",
)

st.divider()

if sort_target == "OP名":
    sorted_df = filtered.sort_values("OP名").reset_index(drop=True)
else:
    sorted_df = filtered.sort_values(sort_target, ascending=False, na_position="last").reset_index(drop=True)

st.subheader(f"一覧（{sort_target} 順）")
fmt_dict = {}
for label in [M_THIS, M_PREV, M_PREV2]:
    fmt_dict[f"{label}_成約数"] = "{:,.0f}"
    fmt_dict[f"{label}_初回受取数"] = "{:,.0f}"
    fmt_dict[f"{label}_初回受取率"] = "{:.1%}"

styled = sorted_df.style.format(fmt_dict, na_rep="—").background_gradient(
    subset=[f"{M_PREV}_初回受取率", f"{M_PREV2}_初回受取率"],
    cmap="RdYlGn",
    vmin=0,
    vmax=1,
)
st.dataframe(styled, use_container_width=True, hide_index=True)

st.divider()

st.subheader(f"{M_PREV}_初回受取率（OP別ランキング）")
plot_df = sorted_df.dropna(subset=[f"{M_PREV}_初回受取率"]).copy()
if not plot_df.empty:
    fig = px.bar(
        plot_df,
        x="OP名",
        y=f"{M_PREV}_初回受取率",
        text=plot_df[f"{M_PREV}_初回受取率"].map(lambda v: f"{v:.0%}" if pd.notna(v) else ""),
        color=f"{M_PREV}_初回受取率",
        color_continuous_scale="RdYlGn",
        range_color=[0, 1],
    )
    fig.update_layout(xaxis_title=None, yaxis_tickformat=".0%", coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info(f"{M_PREV}の評価対象データがありません。")

st.divider()

st.subheader(f"成約数 vs 初回受取率（{M_PREV}、バブルサイズ=初回受取数）")
bubble = filtered.dropna(subset=[f"{M_PREV}_成約数", f"{M_PREV}_初回受取率"]).copy()
if not bubble.empty:
    bubble[f"{M_PREV}_初回受取数_size"] = bubble[f"{M_PREV}_初回受取数"].fillna(0) + 1
    fig = px.scatter(
        bubble,
        x=f"{M_PREV}_成約数",
        y=f"{M_PREV}_初回受取率",
        size=f"{M_PREV}_初回受取数_size",
        text="OP名",
        size_max=40,
        color=f"{M_PREV}_初回受取率",
        color_continuous_scale="RdYlGn",
        range_color=[0, 1],
    )
    fig.update_traces(textposition="top center")
    fig.update_layout(yaxis_tickformat=".0%", coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("バブルチャート用のデータがありません。")

st.divider()

st.subheader("3ヶ月推移（個別OP）")
focus = st.selectbox("OPを選択", sorted_df["OP名"].tolist())
if focus:
    row = sorted_df[sorted_df["OP名"] == focus].iloc[0]
    trend = pd.DataFrame(
        {
            "月": [M_PREV2, M_PREV, M_THIS],
            "成約数": [row[f"{M_PREV2}_成約数"], row[f"{M_PREV}_成約数"], row[f"{M_THIS}_成約数"]],
            "初回受取数": [row[f"{M_PREV2}_初回受取数"], row[f"{M_PREV}_初回受取数"], row[f"{M_THIS}_初回受取数"]],
            "初回受取率": [row[f"{M_PREV2}_初回受取率"], row[f"{M_PREV}_初回受取率"], row[f"{M_THIS}_初回受取率"]],
        }
    )
    c1, c2 = st.columns(2)
    with c1:
        long = trend.melt(id_vars="月", value_vars=["成約数", "初回受取数"], var_name="指標", value_name="件数")
        fig = px.bar(long, x="月", y="件数", color="指標", barmode="group", text_auto=True)
        fig.update_layout(xaxis_title=None)
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.line(trend, x="月", y="初回受取率", markers=True)
        fig.update_layout(xaxis_title=None, yaxis_tickformat=".0%", yaxis_range=[0, 1])
        st.plotly_chart(fig, use_container_width=True)
