"""データセット情報マッピング & 表示名生成."""
from __future__ import annotations

import re
from functools import cache

import streamlit as st
from google.cloud import bigquery

from lib.bq import PROJECT_ID, get_bq_client

PRODUCT_NAMES: dict[str, str] = {
    "KB2": "キラーバーナーII",
    "KB": "キラーバーナー",
    "KBD": "キラーバーナーDROP",
    "MW": "ミカホワイト",
    "OM": "メンディー",
    "PSS": "ペルル美容液",
    "PS": "ペルルセボン",
    "TL": "テナル",
}

PLAN_NAMES: dict[str, str] = {
    "1nen": "1年",
    "platinum": "プラチナ",
    "premium": "プレミアム",
    "royal_IB_new": "ロイヤルIB新規",
    "royal_IB_old": "ロイヤルIB既存",
    "royal_OB": "ロイヤルOB",
}

# プラン → item_master.継続率抽出用 のプレフィックス（child_ordersビューSQLから抽出）
PLAN_RETENTION_PREFIX: dict[str, str] = {
    "1nen": "1年",
    "platinum": "プラチナ",
    "premium": "プレミアム",
    "royal_IB_new": "IBロイヤル",  # 表示名と異なる点に注意
    "royal_IB_old": "ロイヤルIB",
    "royal_OB": "ロイヤルOB",
}

# 除外するデータセット（分析対象外）
EXCLUDE_DATASETS = {
    "item_master",
    "kb_row_test",
    "nakano_test",
    "raw_keizoku_child_orders",
    "raw_keizoku_child_orders_staging",
    "raw_orders",
    "raw_orders_staging",
    "raw_subscription_orders",
    "raw_subscription_orders_staging",
}

_PRODUCT_KEYS_ORDERED = sorted(PRODUCT_NAMES.keys(), key=len, reverse=True)


def parse_dataset_id(dataset_id: str) -> tuple[str | None, str | None]:
    """'KB2_1nen' → ('KB2', '1nen')。マッチしない場合は (None, None)."""
    for prod in _PRODUCT_KEYS_ORDERED:
        prefix = f"{prod}_"
        if dataset_id.startswith(prefix):
            plan = dataset_id[len(prefix):]
            return prod, plan
    return None, None


def display_name(dataset_id: str) -> str:
    """表示名生成: 'KB2_1nen' → 'キラーバーナーII 1年'."""
    prod, plan = parse_dataset_id(dataset_id)
    if prod is None:
        return dataset_id
    prod_jp = PRODUCT_NAMES.get(prod, prod)
    plan_jp = PLAN_NAMES.get(plan, plan)
    return f"{prod_jp} {plan_jp}"


@st.cache_data(ttl=60 * 60, show_spinner="データセット一覧を取得中…")
def list_analyzable_datasets() -> list[str]:
    """分析対象のデータセットID一覧を返す。"""
    client = get_bq_client()
    ids = []
    for ds in client.list_datasets():
        if ds.dataset_id in EXCLUDE_DATASETS:
            continue
        prod, _ = parse_dataset_id(ds.dataset_id)
        if prod is None:
            continue
        ids.append(ds.dataset_id)
    return sorted(ids, key=lambda d: (parse_dataset_id(d)[0] or "", parse_dataset_id(d)[1] or ""))
