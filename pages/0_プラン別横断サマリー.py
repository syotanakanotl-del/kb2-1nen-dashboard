"""プラン別横断サマリー: 全商品を集約した1年/プレミアム/ロイヤルOB等の比較."""
from __future__ import annotations

import matplotlib.cm as cm
import matplotlib.colors as mcolors
import pandas as pd
import streamlit as st

from lib.bq import load_cross_product_summary, recent_month_labels
from lib.datasets import PLAN_NAMES, PRODUCT_NAMES
from lib.ui import coupon_radio

st.set_page_config(page_title="プラン別横断サマリー", page_icon="🧭", layout="wide")
st.title("プラン別 横断サマリー")
st.caption(
    "全商品 (KB2/KB/KBD/MW/OM/PSS/PS/TL) を集約し、"
    "**プラン (1年, プラチナ, プレミアム, ロイヤルIB新規/既存, ロイヤルOB)** 単位で比較。"
    "初回読み込みは45データセット分のSheets取得で時間がかかります（以降キャッシュ）。"
)

with st.sidebar:
    st.header("フィルタ")
coupon_arg = coupon_radio(key="coupon_cross")
if coupon_arg:
    st.info(f"🎫 クーポン **{coupon_arg}** のみで集計")

try:
    raw = load_cross_product_summary(coupon=coupon_arg)
except Exception as e:
    st.error(f"集計失敗: {type(e).__name__}: {e}")
    st.stop()

if raw.empty:
    st.info("データがありません。")
    st.stop()

labels = recent_month_labels()
this_m = labels["_this_ts"]
prev_m = labels["_prev_ts"]
prev2_m = labels["_prev2_ts"]
month_keys = {prev2_m: labels["prev2"], prev_m: labels["prev"], this_m: labels["this"]}

# 直近3ヶ月ウィンドウ
window = raw[raw["月"].isin(month_keys.keys())].copy()


def aggregate_by(dim: str) -> pd.DataFrame:
    """dim='プラン' or '商品' で集約し、3ヶ月分の{成約数,初回受取数,初回受取率}を返す。"""
    rows: list[dict] = []
    for key, g in window.groupby(dim):
        row: dict = {dim: key}
        for m_ts, label in month_keys.items():
            sub = g[g["月"] == m_ts]
            s = int(sub["成約数"].sum())
            u = int(sub["初回受取数"].sum())
            row[f"{label}_成約数"] = s
            row[f"{label}_初回受取数"] = u
            row[f"{label}_初回受取率"] = (u / s) if s else None
        rows.append(row)
    out = pd.DataFrame(rows)
    cols = [dim]
    for key in ["this", "prev", "prev2"]:
        label = labels[key]
        cols += [f"{label}_成約数", f"{label}_初回受取数", f"{label}_初回受取率"]
    return out[cols]


def display_label(value: str, dim: str) -> str:
    mapping = PLAN_NAMES if dim == "プラン" else PRODUCT_NAMES
    return mapping.get(value, value)


cmap = cm.get_cmap("RdYlGn")
norm = mcolors.Normalize(vmin=0, vmax=1)


def rate_bg(v: float | None) -> str:
    if v is None or pd.isna(v):
        return ""
    r, g, b, _ = cmap(norm(v))
    return f"background-color: rgb({int(r * 255)}, {int(g * 255)}, {int(b * 255)}); color: #111;"


def render_table(df: pd.DataFrame, dim: str) -> None:
    df = df.copy()
    df[dim] = df[dim].map(lambda v: display_label(v, dim))
    df = df.sort_values(f"{labels['prev']}_初回受取率", ascending=False, na_position="last")
    fmt: dict = {}
    rate_cols: list[str] = []
    for key in ["this", "prev", "prev2"]:
        label = labels[key]
        fmt[f"{label}_成約数"] = "{:,.0f}"
        fmt[f"{label}_初回受取数"] = "{:,.0f}"
        fmt[f"{label}_初回受取率"] = "{:.1%}"
        rate_cols.append(f"{label}_初回受取率")
    styled = (
        df.style.format(fmt, na_rep="—")
        .map(rate_bg, subset=rate_cols)
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ─── プラン別 ─────────────────────────────────────────
st.subheader("プラン別 直近3ヶ月")
st.caption("行=プラン、列=月別の成約数 / 初回受取数 / 初回受取率（全商品合計）")
plan_summary = aggregate_by("プラン")
render_table(plan_summary, "プラン")

# ─── 商品別 ─────────────────────────────────────────
st.divider()
st.subheader("商品別 直近3ヶ月")
st.caption("行=商品、列=月別の成約数 / 初回受取数 / 初回受取率（全プラン合計）")
prod_summary = aggregate_by("商品")
render_table(prod_summary, "商品")

# ─── 商品×プラン クロス集計 ───────────────────────────
st.divider()
st.subheader(f"商品×プラン クロス集計 ({labels['prev']}_初回受取率)")
st.caption(f"行=商品、列=プラン、値={labels['prev']}の初回受取率（評価可能な前月で比較）")

crosstab_window = window[window["月"] == prev_m].copy()
crosstab_window["商品表示"] = crosstab_window["商品"].map(lambda v: PRODUCT_NAMES.get(v, v))
crosstab_window["プラン表示"] = crosstab_window["プラン"].map(lambda v: PLAN_NAMES.get(v, v))

pivot_rate = crosstab_window.pivot_table(
    index="商品表示", columns="プラン表示", values=["成約数", "初回受取数"], aggfunc="sum"
)
if not pivot_rate.empty:
    rate_pivot = (
        pivot_rate["初回受取数"] / pivot_rate["成約数"]
    ).round(4)
    styled = rate_pivot.style.format("{:.1%}", na_rep="—").map(rate_bg)
    st.dataframe(styled, use_container_width=True)
else:
    st.info("クロス集計用のデータがありません。")
