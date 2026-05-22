from __future__ import annotations

from datetime import timedelta

import matplotlib.cm as cm
import matplotlib.colors as mcolors
import pandas as pd
import plotly.express as px
import streamlit as st

from lib.bq import load_daily_op_receive_rate


_RATE_CMAP = cm.get_cmap("RdYlGn")
_RATE_NORM = mcolors.Normalize(vmin=0, vmax=1)


def _rate_bg(val: float | None) -> str:
    if val is None or pd.isna(val):
        return ""
    r, g, b, _ = _RATE_CMAP(_RATE_NORM(val))
    return f"background-color: rgb({int(r * 255)}, {int(g * 255)}, {int(b * 255)}); color: #111;"

st.set_page_config(page_title="OP別デイリー受取率", page_icon="📅", layout="wide")
st.title("OP別 デイリー受取率")
st.caption(
    "**成約日 × OP** で日次の初回受取率を可視化。"
    "21日以上経過した成約日（成熟）が評価可能。"
    "21日未経過は0%付近に出ます。"
)

df = load_daily_op_receive_rate()

if df.empty:
    st.info("データがありません。")
    st.stop()

today = pd.Timestamp.now(tz="Asia/Tokyo").normalize().tz_localize(None)
maturity_cutoff = today - pd.Timedelta(days=21)
min_date = df["成約日"].min().date()
max_date = df["成約日"].max().date()

with st.sidebar:
    st.header("フィルタ")
    default_from = max(min_date, (today - pd.Timedelta(days=90)).date())
    default_to = maturity_cutoff.date()
    date_range = st.date_input(
        "成約日範囲",
        value=(default_from, default_to),
        min_value=min_date,
        max_value=max_date,
        help="既定は『成熟済み（21日以上前）』までの直近90日",
    )
    only_mature = st.checkbox("成熟済み (21日以上前) のみ", value=True)

    totals = df.groupby("OP名")["成約数"].sum().sort_values(ascending=False)
    op_names = totals.index.tolist()
    recent_cutoff = today - pd.Timedelta(days=90)
    recent_ops_set = set(
        df.loc[df["成約日"] >= recent_cutoff, "OP名"].dropna().unique()
    )
    op_default = [op for op in op_names if op in recent_ops_set]
    selected = st.multiselect(
        "OP名",
        op_names,
        default=op_default,
        help=f"既定は直近3ヶ月（{recent_cutoff.date()} 以降）に成約のあるOP（{len(op_default)}名）",
    )

    min_subs = st.slider(
        "セルの最小成約数（ヒートマップで除外）",
        min_value=1,
        max_value=20,
        value=1,
        help="サンプルが少ない日は色が極端に振れがち。閾値以下を除外できます",
    )

if isinstance(date_range, tuple) and len(date_range) == 2:
    start, end = date_range
else:
    start, end = default_from, default_to

mask = (df["成約日"].dt.date >= start) & (df["成約日"].dt.date <= end)
if only_mature:
    mask &= df["成熟"]
if selected:
    mask &= df["OP名"].isin(selected)
view = df[mask].copy()

if view.empty:
    st.info("条件に合致するデータがありません。フィルタを緩めてください。")
    st.stop()


def overall(d: pd.DataFrame) -> tuple[int, int, float | None]:
    s = int(d["成約数"].sum())
    u = int(d["初回受取数"].sum())
    return s, u, (u / s if s else None)


total_s, total_u, total_r = overall(view)
mature_s, mature_u, mature_r = overall(view[view["成熟"]])


def fmt_pct(v: float | None) -> str:
    return f"{v:.1%}" if v is not None else "—"


c1, c2, c3, c4 = st.columns(4)
c1.metric("対象期間", f"{start} ~ {end}")
c2.metric("対象成約数", f"{total_s:,}")
c3.metric("対象初回受取数", f"{total_u:,}")
c4.metric(
    "成熟分のみ初回受取率",
    fmt_pct(mature_r),
    help=f"{mature_u:,} / {mature_s:,}（成熟＝成約日が21日以上前）",
)

st.divider()

st.subheader("ピボット表（行=成約日、列=企業×OP×{成約数, 受取率}）")
st.caption("空白セル＝その日その人に成約なし。受取率は成約があった日のみ色付き。")

pivot_src = view.copy()
pivot_src["成約日"] = pd.to_datetime(pivot_src["成約日"]).dt.date

# Build wide table with 3-level columns
parts: list[pd.DataFrame] = []
for metric in ["成約数", "初回受取率"]:
    p = pivot_src.pivot_table(
        index="成約日",
        columns=["企業名", "OP名"],
        values=metric,
        aggfunc="first",
    )
    p.columns = pd.MultiIndex.from_tuples(
        [(c[0], c[1], metric) for c in p.columns],
        names=["企業名", "OP名", "指標"],
    )
    parts.append(p)

if parts:
    pivot = pd.concat(parts, axis=1).sort_index(axis=0)
    # Order: 企業名→OP名→指標 (成約数 → 受取率)
    metric_order = {"成約数": 0, "初回受取率": 1}
    pivot = pivot[
        sorted(
            pivot.columns,
            key=lambda c: (str(c[0]), str(c[1]), metric_order.get(c[2], 99)),
        )
    ]

    fmt_map: dict = {}
    for col in pivot.columns:
        if col[2] == "初回受取率":
            fmt_map[col] = "{:.2%}"
        else:
            fmt_map[col] = "{:.0f}"

    rate_cols = [c for c in pivot.columns if c[2] == "初回受取率"]
    styled_pivot = (
        pivot.style.format(fmt_map, na_rep="")
        .map(_rate_bg, subset=rate_cols)
        .set_table_styles(
            [
                {"selector": "table", "props": "border-collapse: separate; border-spacing: 0; font-size: 13px;"},
                {"selector": "th", "props": "text-align: center; font-weight: 600; border: 1px solid #ccc; padding: 4px 8px; white-space: nowrap;"},
                {"selector": "td", "props": "text-align: right; border: 1px solid #eee; padding: 2px 6px; font-variant-numeric: tabular-nums; background: white;"},
                # Sticky header rows (3 levels of column MultiIndex)
                {"selector": "thead th", "props": "position: sticky; background: #d6e4ff; z-index: 3;"},
                {"selector": "thead th.level0", "props": "top: 0; background: #c2d6ff;"},
                {"selector": "thead th.level1", "props": "top: 34px;"},
                {"selector": "thead th.level2", "props": "top: 68px; background: #e6eeff;"},
                # Sticky first column (成約日)
                {"selector": "tbody th", "props": "position: sticky; left: 0; z-index: 2; background: #fafbfc; font-weight: 600; text-align: center;"},
                # Top-left corner cells (intersection of sticky row & column)
                {"selector": "thead th.blank, thead th.index_name", "props": "left: 0; z-index: 5;"},
            ]
        )
        .set_properties(**{"min-width": "70px"})
    )
    html = styled_pivot.to_html()
    st.markdown(
        f'<div style="overflow:auto; max-height:650px; border:1px solid #ccc;">{html}</div>',
        unsafe_allow_html=True,
    )

    st.download_button(
        "ピボット表をCSVダウンロード",
        pivot.to_csv().encode("utf-8-sig"),
        file_name="daily_op_pivot.csv",
        mime="text/csv",
        key="pivot_dl",
    )
else:
    st.info("ピボット用のデータがありません。")

st.divider()

st.subheader("ヒートマップ（行=OP名、列=成約日、色=初回受取率）")
heat_src = view.copy()
heat_src = heat_src[heat_src["成約数"] >= min_subs]
if heat_src.empty:
    st.info("最小成約数の条件で全てのセルが除外されました。")
else:
    pivot_rate = heat_src.pivot_table(
        index="OP名", columns="成約日", values="初回受取率"
    ).sort_index()
    pivot_rate.columns = [d.strftime("%Y-%m-%d") for d in pivot_rate.columns]
    pivot_cnt = heat_src.pivot_table(
        index="OP名", columns="成約日", values="成約数"
    ).reindex_like(pivot_rate.set_index(pivot_rate.index))
    fig = px.imshow(
        pivot_rate,
        color_continuous_scale="RdYlGn",
        zmin=0,
        zmax=1,
        aspect="auto",
        text_auto=".0%",
        labels={"color": "初回受取率"},
    )
    fig.update_layout(
        xaxis_title="成約日",
        yaxis_title="OP名",
        coloraxis_colorbar_tickformat=".0%",
        height=max(400, 28 * len(pivot_rate.index)),
    )
    fig.update_xaxes(tickangle=-45)
    st.plotly_chart(fig, use_container_width=True)

st.divider()

st.subheader("日次推移（折れ線）")
trend = view.dropna(subset=["初回受取率"]).copy()
if trend.empty:
    st.info("推移用のデータがありません。")
else:
    fig = px.line(
        trend.sort_values(["OP名", "成約日"]),
        x="成約日",
        y="初回受取率",
        color="OP名",
        markers=True,
        hover_data=["成約数", "初回受取数"],
    )
    fig.update_layout(yaxis_tickformat=".0%", yaxis_range=[0, 1.05])
    st.plotly_chart(fig, use_container_width=True)

st.divider()

st.subheader("全体（全OP合計）の日次受取率")
overall_daily = (
    view.groupby("成約日")
    .agg(成約数=("成約数", "sum"), 初回受取数=("初回受取数", "sum"))
    .reset_index()
)
overall_daily["初回受取率"] = overall_daily.apply(
    lambda r: (r["初回受取数"] / r["成約数"]) if r["成約数"] else None, axis=1
)
if overall_daily.empty:
    st.info("全体推移用のデータがありません。")
else:
    fig = px.bar(
        overall_daily,
        x="成約日",
        y="初回受取数",
        opacity=0.4,
    )
    fig.add_scatter(
        x=overall_daily["成約日"],
        y=overall_daily["初回受取率"],
        mode="lines+markers",
        name="初回受取率",
        yaxis="y2",
        line=dict(color="firebrick"),
    )
    fig.update_layout(
        yaxis=dict(title="初回受取数"),
        yaxis2=dict(
            title="初回受取率",
            overlaying="y",
            side="right",
            tickformat=".0%",
            range=[0, 1],
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, use_container_width=True)

st.divider()

st.subheader("生データ")
display = view.sort_values(["成約日", "OP名"]).copy()
display["成約日"] = display["成約日"].dt.strftime("%Y-%m-%d")
display["成熟"] = display["成熟"].map({True: "○", False: "—"})
styled = display.style.format(
    {"成約数": "{:,.0f}", "初回受取数": "{:,.0f}", "初回受取率": "{:.1%}"},
    na_rep="—",
).background_gradient(
    subset=["初回受取率"], cmap="RdYlGn", vmin=0, vmax=1
)
st.dataframe(styled, use_container_width=True, hide_index=True)

st.download_button(
    "CSVダウンロード",
    display.to_csv(index=False).encode("utf-8-sig"),
    file_name="daily_op_receive_rate.csv",
    mime="text/csv",
)
