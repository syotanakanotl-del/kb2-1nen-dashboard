from __future__ import annotations

import matplotlib.cm as cm
import matplotlib.colors as mcolors
import pandas as pd
import plotly.express as px
import streamlit as st

from lib.bq import load_monthly_op_receive_rate


_RATE_CMAP = cm.get_cmap("RdYlGn")
_RATE_NORM = mcolors.Normalize(vmin=0, vmax=1)


def _rate_bg(val: float | None) -> str:
    if val is None or pd.isna(val):
        return ""
    r, g, b, _ = _RATE_CMAP(_RATE_NORM(val))
    return f"background-color: rgb({int(r * 255)}, {int(g * 255)}, {int(b * 255)}); color: #111;"


st.set_page_config(page_title="OP別月間受取率", page_icon="📆", layout="wide")
st.title("OP別 月間受取率")
st.caption(
    "**月 × OP** で初回受取率の履歴を可視化。"
    "当月は21日未経過のため低めに出ます。"
    "**前月以前を主な評価指標として** ご覧ください。"
)

df = load_monthly_op_receive_rate()

if df.empty:
    st.info("データがありません。")
    st.stop()

months_sorted = sorted(df["月"].dropna().unique())

with st.sidebar:
    st.header("フィルタ")

    only_mature = st.checkbox("成熟済み (前月以前) のみ", value=False)

    op_names = sorted(df["OP名"].dropna().unique().tolist())
    totals = df.groupby("OP名")["成約数"].sum().sort_values(ascending=False)
    today = pd.Timestamp.now(tz="Asia/Tokyo").normalize().tz_localize(None)
    recent_cutoff = today - pd.Timedelta(days=90)
    recent_ops_set = set(
        df.loc[df["月"] >= recent_cutoff - pd.Timedelta(days=31), "OP名"].dropna().unique()
    )
    op_default = [op for op in totals.index if op in recent_ops_set]

    selected_ops = st.multiselect(
        "OP名",
        op_names,
        default=op_default,
        help=f"既定は直近3ヶ月に成約があるOP（{len(op_default)}名）",
    )

    month_labels = [pd.Timestamp(m).strftime("%Y-%m") for m in months_sorted]
    sel_months = st.multiselect(
        "対象月",
        month_labels,
        default=month_labels[-12:] if len(month_labels) > 12 else month_labels,
        help="既定は直近12ヶ月",
    )

mask = pd.Series(True, index=df.index)
if only_mature:
    mask &= df["成熟"]
if selected_ops:
    mask &= df["OP名"].isin(selected_ops)
if sel_months:
    mask &= df["月"].dt.strftime("%Y-%m").isin(sel_months)
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
c1.metric("対象月数", f"{view['月'].nunique():,}")
c2.metric("対象成約数", f"{total_s:,}")
c3.metric("対象初回受取数", f"{total_u:,}")
c4.metric(
    "成熟分のみ初回受取率",
    fmt_pct(mature_r),
    help=f"{mature_u:,} / {mature_s:,}（成熟＝前月以前）",
)

st.divider()

st.subheader("ピボット表（行=月、列=企業×OP×{成約数, 受取率}）")
st.caption(
    "空白セル＝その月その人に成約なし。"
    "右端に **(企業合計)** と **(全合計)** を表示。"
)

pivot_src = view.copy()
pivot_src["月"] = pd.to_datetime(pivot_src["月"]).dt.strftime("%Y-%m")

# 企業合計
company_totals = (
    pivot_src.groupby(["企業名", "月"], as_index=False)
    .agg(成約数=("成約数", "sum"), 初回受取数=("初回受取数", "sum"))
)
company_totals["OP名"] = "(企業合計)"
company_totals["初回受取率"] = company_totals.apply(
    lambda r: (r["初回受取数"] / r["成約数"]) if r["成約数"] else None, axis=1
)

# 全合計
grand_totals = (
    pivot_src.groupby(["月"], as_index=False)
    .agg(成約数=("成約数", "sum"), 初回受取数=("初回受取数", "sum"))
)
grand_totals["企業名"] = "(全合計)"
grand_totals["OP名"] = "(全合計)"
grand_totals["初回受取率"] = grand_totals.apply(
    lambda r: (r["初回受取数"] / r["成約数"]) if r["成約数"] else None, axis=1
)

pivot_full = pd.concat(
    [
        pivot_src[["企業名", "OP名", "月", "成約数", "初回受取数", "初回受取率"]],
        company_totals[["企業名", "OP名", "月", "成約数", "初回受取数", "初回受取率"]],
        grand_totals[["企業名", "OP名", "月", "成約数", "初回受取数", "初回受取率"]],
    ],
    ignore_index=True,
)

parts: list[pd.DataFrame] = []
for metric in ["成約数", "初回受取率"]:
    p = pivot_full.pivot_table(
        index="月",
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

    metric_order = {"成約数": 0, "初回受取率": 1}

    def col_key(c: tuple) -> tuple:
        company, op, metric = c
        if company == "(全合計)":
            company_rank = (1, "")
        else:
            company_rank = (0, company)
        if op == "(企業合計)" or op == "(全合計)":
            op_rank = (1, "")
        else:
            op_rank = (0, op)
        return (company_rank, op_rank, metric_order.get(metric, 99))

    pivot = pivot[sorted(pivot.columns, key=col_key)]

    fmt_map: dict = {}
    for col in pivot.columns:
        if col[2] == "初回受取率":
            fmt_map[col] = "{:.2%}"
        else:
            fmt_map[col] = "{:.0f}"

    rate_cols = [c for c in pivot.columns if c[2] == "初回受取率"]
    total_cols = [
        c for c in pivot.columns
        if c[1] == "(企業合計)" or c[0] == "(全合計)"
    ]

    styled_pivot = (
        pivot.style.format(fmt_map, na_rep="")
        .map(_rate_bg, subset=rate_cols)
        .set_properties(subset=total_cols, **{"font-weight": "700"})
        .set_table_styles(
            [
                {"selector": "table", "props": "border-collapse: separate; border-spacing: 0; font-size: 13px;"},
                {"selector": "th", "props": "text-align: center; font-weight: 600; border: 1px solid #ccc; padding: 4px 8px; white-space: nowrap;"},
                {"selector": "td", "props": "text-align: right; border: 1px solid #eee; padding: 2px 6px; font-variant-numeric: tabular-nums; background: white;"},
                {"selector": "thead th", "props": "position: sticky; background: #d6e4ff; z-index: 3;"},
                {"selector": "thead th.level0", "props": "top: 0; background: #c2d6ff;"},
                {"selector": "thead th.level1", "props": "top: 34px;"},
                {"selector": "thead th.level2", "props": "top: 68px; background: #e6eeff;"},
                {"selector": "tbody th", "props": "position: sticky; left: 0; z-index: 2; background: #fafbfc; font-weight: 600; text-align: center;"},
                {"selector": "thead th.blank, thead th.index_name", "props": "left: 0; z-index: 5;"},
            ]
        )
        .set_properties(**{"min-width": "70px"})
    )
    html = styled_pivot.to_html()
    st.html(
        f'<div style="overflow:auto; max-height:650px; border:1px solid #ccc;">{html}</div>'
    )

    st.download_button(
        "ピボット表をCSVダウンロード",
        pivot.to_csv().encode("utf-8-sig"),
        file_name="monthly_op_pivot.csv",
        mime="text/csv",
        key="monthly_pivot_dl",
    )
else:
    st.info("ピボット用のデータがありません。")

st.divider()

st.subheader("OP別 月間推移（折れ線）")
trend_src = view.dropna(subset=["初回受取率"]).copy()
trend_src["月"] = pd.to_datetime(trend_src["月"]).dt.strftime("%Y-%m")
if not trend_src.empty:
    fig = px.line(
        trend_src.sort_values(["OP名", "月"]),
        x="月",
        y="初回受取率",
        color="OP名",
        markers=True,
        hover_data=["成約数", "初回受取数"],
    )
    fig.update_layout(yaxis_tickformat=".0%", yaxis_range=[0, 1.05])
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("推移用のデータがありません。")

st.divider()

st.subheader("全体（全OP合計）の月別推移")
overall_monthly = (
    view.groupby("月", as_index=False)
    .agg(成約数=("成約数", "sum"), 初回受取数=("初回受取数", "sum"))
)
overall_monthly["初回受取率"] = overall_monthly.apply(
    lambda r: (r["初回受取数"] / r["成約数"]) if r["成約数"] else None, axis=1
)
overall_monthly["月"] = pd.to_datetime(overall_monthly["月"]).dt.strftime("%Y-%m")
if not overall_monthly.empty:
    fig = px.bar(overall_monthly, x="月", y="初回受取数", opacity=0.4)
    fig.add_scatter(
        x=overall_monthly["月"],
        y=overall_monthly["初回受取率"],
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
