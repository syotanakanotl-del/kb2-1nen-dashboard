"""共通サイドバーUI: データセットセレクタ + クーポンフィルタ."""
from __future__ import annotations

import streamlit as st

from lib.bq import DEFAULT_DATASET
from lib.datasets import display_name, list_analyzable_datasets


def dataset_selector(key: str = "dataset_select") -> str:
    """データセット選択UIをサイドバーに表示し、選択された dataset_id を返す。"""
    try:
        datasets = list_analyzable_datasets()
    except Exception as e:
        st.sidebar.error(f"データセット一覧取得失敗: {e}")
        return DEFAULT_DATASET

    if not datasets:
        return DEFAULT_DATASET

    default_idx = datasets.index(DEFAULT_DATASET) if DEFAULT_DATASET in datasets else 0
    return st.sidebar.selectbox(
        "データセット",
        datasets,
        index=default_idx,
        format_func=lambda d: f"{display_name(d)}  ({d})",
        key=key,
    )


def coupon_radio(key: str) -> str | None:
    """クーポン有/無/両方のラジオUI。 None なら 両方。"""
    choice = st.sidebar.radio(
        "クーポン", ["両方", "有", "無"], horizontal=True, key=key
    )
    return choice if choice in ("有", "無") else None


def show_dataset_header(dataset_id: str, coupon: str | None = None) -> None:
    """ページ上部に現在のデータセットとフィルタ条件を表示."""
    parts = [f"📂 **{display_name(dataset_id)}** ({dataset_id})"]
    if coupon:
        parts.append(f"🎫 クーポン **{coupon}** のみ")
    st.caption("　/　".join(parts))
