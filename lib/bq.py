from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from google.cloud import bigquery
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build

PROJECT_ID = "trustline-project"
ROOT = Path(__file__).resolve().parent.parent
SA_KEY_PATH = ROOT / "secrets" / "dashboard-bq-key.json"
USER_ADC_PATH = Path(os.environ.get("APPDATA", "")) / "gcloud" / "application_default_credentials.json"

SHEET_SUBSCRIPTION_MASTER_ID = "1bRbSn6I8sa0C75h5zA8nQBfG9Lo3e39n_7ZkiLz2Ubw"
SHEET_ITEM_MASTER_ID = "1lrBYe5MLzXRp2IfE05GpRrycCzZy9tFEyY0itCaTjF4"

SUBSCRIPTION_TABS = [f"キラーバーナーⅡ{c}" for c in "①②③④⑤⑥⑦⑧⑨⑩⑪"]
SUBSCRIPTION_RANGE_SUFFIX = "!A:E"
SUBSCRIPTION_COLUMNS = ["seiyaku_date", "master_id", "coupon", "company", "person"]

ITEM_MASTER_RANGE = "KB!A:P"


def _sa_credentials():
    """Service Account credentials for Sheets API.

    Priority: st.secrets["gcp_service_account"] > local SA key file.
    """
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    try:
        info = dict(st.secrets["gcp_service_account"])
        return service_account.Credentials.from_service_account_info(info, scopes=scopes)
    except (FileNotFoundError, KeyError, st.errors.StreamlitSecretNotFoundError):
        pass
    return service_account.Credentials.from_service_account_file(str(SA_KEY_PATH), scopes=scopes)


def _bq_credentials():
    """Credentials for BigQuery client.

    Priority: st.secrets["gcp_user_credentials"] (refresh token flow) > local ADC.
    Returns (credentials, project) tuple; either may be None to defer to default.
    """
    try:
        info = dict(st.secrets["gcp_user_credentials"])
        creds = UserCredentials.from_authorized_user_info(info)
        return creds, info.get("quota_project_id") or PROJECT_ID
    except (KeyError, st.errors.StreamlitSecretNotFoundError):
        pass

    if USER_ADC_PATH.exists():
        with open(USER_ADC_PATH, "r", encoding="utf-8") as f:
            info = json.load(f)
        if info.get("type") == "authorized_user":
            creds = UserCredentials.from_authorized_user_info(info)
            return creds, info.get("quota_project_id") or PROJECT_ID

    return None, PROJECT_ID  # google.auth.default() will be used


@st.cache_resource
def get_bq_client() -> bigquery.Client:
    creds, project = _bq_credentials()
    if creds is not None:
        return bigquery.Client(project=project, credentials=creds)
    return bigquery.Client(project=project)


@st.cache_resource
def get_sheets_service():
    creds = _sa_credentials()
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


@st.cache_data(ttl=60 * 30, show_spinner="Sheets: subscription_master 読み込み中…")
def load_subscription_master() -> pd.DataFrame:
    svc = get_sheets_service()
    ranges = [f"{tab}{SUBSCRIPTION_RANGE_SUFFIX}" for tab in SUBSCRIPTION_TABS]
    res = (
        svc.spreadsheets()
        .values()
        .batchGet(spreadsheetId=SHEET_SUBSCRIPTION_MASTER_ID, ranges=ranges)
        .execute()
    )
    frames: list[pd.DataFrame] = []
    for tab, vr in zip(SUBSCRIPTION_TABS, res.get("valueRanges", [])):
        values = vr.get("values", [])
        if len(values) < 2:
            continue
        rows = values[1:]
        rows = [r + [None] * (len(SUBSCRIPTION_COLUMNS) - len(r)) for r in rows]
        df = pd.DataFrame(rows, columns=SUBSCRIPTION_COLUMNS)
        df["source_tab"] = f"KB2 1年OB {tab}"
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=SUBSCRIPTION_COLUMNS + ["source_tab"])
    master = pd.concat(frames, ignore_index=True)

    master["成約日"] = pd.to_datetime(
        master["seiyaku_date"], errors="coerce", format="mixed"
    ).dt.date
    master["マスタID"] = pd.to_numeric(master["master_id"], errors="coerce").astype("Int64")
    master = master[master["マスタID"].notna()].copy()
    master = master.rename(
        columns={"coupon": "クーポン", "company": "企業名", "person": "担当者名"}
    )
    return master[["成約日", "マスタID", "クーポン", "企業名", "担当者名", "source_tab"]].reset_index(drop=True)


@st.cache_data(ttl=60 * 30, show_spinner="Sheets: item_master 読み込み中…")
def load_item_master() -> pd.DataFrame:
    svc = get_sheets_service()
    res = (
        svc.spreadsheets()
        .values()
        .get(spreadsheetId=SHEET_ITEM_MASTER_ID, range=ITEM_MASTER_RANGE)
        .execute()
    )
    values = res.get("values", [])
    if len(values) < 2:
        return pd.DataFrame()
    header = values[0]
    rows = [r + [None] * (len(header) - len(r)) for r in values[1:]]
    df = pd.DataFrame(rows, columns=header)
    return df


@st.cache_data(ttl=60 * 30, show_spinner="BigQuery: child_orders 読み込み中…")
def load_child_orders_raw() -> pd.DataFrame:
    client = get_bq_client()
    sql = """
    SELECT
      `定期購入_マスター_受注ID`,
      `定期購入_自動受注_回数`,
      `発送日`,
      `支払い方法`,
      `対応状況`,
      `注文ID`,
      `商品コード`,
      `定期初回注文日時`
    FROM `trustline-project.raw_keizoku_child_orders.KB_child_orders`
    """
    return client.query(sql).to_dataframe()


def load_child_orders_filtered() -> pd.DataFrame:
    items = load_item_master()
    one_year_items: list[str] = []
    if "商品コード" in items.columns and "継続率抽出用" in items.columns:
        one_year_items = (
            items.loc[
                items["継続率抽出用"].astype(str).str.startswith("1年"),
                "商品コード",
            ]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )

    child = load_child_orders_raw()
    if not one_year_items:
        return child.iloc[0:0]
    return child[child["商品コード"].astype(str).isin(set(one_year_items))].copy()


def load_monthly_subscriptions() -> pd.DataFrame:
    m = load_subscription_master().copy()
    m["成約日"] = pd.to_datetime(m["成約日"])
    m = m.dropna(subset=["成約日"])
    m["month"] = m["成約日"].dt.to_period("M").dt.to_timestamp()
    return (
        m.groupby("month").size().reset_index(name="subscriptions").sort_values("month")
    )


def load_monthly_shipments() -> pd.DataFrame:
    c = load_child_orders_filtered().copy()
    c = c[c["対応状況"] == 5]
    c["発送日"] = pd.to_datetime(c["発送日"])
    c = c.dropna(subset=["発送日"])
    c["month"] = c["発送日"].dt.tz_localize(None).dt.to_period("M").dt.to_timestamp()
    return (
        c.groupby("month").size().reset_index(name="shipments").sort_values("month")
    )


def classify_coupon(value) -> str:
    """クーポン値を「有」/「無」に分類."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "無"
    v = str(value).strip()
    if not v or v in {"クーポン無", "なし", "無", "なし(クーポンなし)"}:
        return "無"
    return "有"


def _apply_coupon_filter(master: pd.DataFrame, coupon: str | None) -> pd.DataFrame:
    """coupon = '有' | '無' | None でフィルタ。"""
    if coupon not in ("有", "無"):
        return master
    return master[master["クーポン"].map(classify_coupon) == coupon].copy()


def _shipped_count_per_master() -> pd.DataFrame:
    """マスタIDごとの「21日以上前・対応状況=5」発送件数 ＝ 受取済回数。"""
    today = pd.Timestamp.now(tz="Asia/Tokyo").normalize()
    threshold = today - pd.Timedelta(days=21)
    threshold_naive = threshold.tz_localize(None)

    c = load_child_orders_filtered().copy()
    c["発送日"] = pd.to_datetime(c["発送日"])
    if c["発送日"].dt.tz is not None:
        c["発送日"] = c["発送日"].dt.tz_localize(None)
    c = c[(c["対応状況"] == 5) & c["発送日"].notna() & (c["発送日"] <= threshold_naive)]
    grouped = c.groupby("定期購入_マスター_受注ID").size().reset_index(name="shipped_count")
    grouped = grouped.rename(columns={"定期購入_マスター_受注ID": "マスタID"})
    return grouped


def recent_month_labels() -> dict:
    """直近3ヶ月の表示用ラベル: {"this": "5月", "prev": "4月", "prev2": "3月"}."""
    today = pd.Timestamp.now(tz="Asia/Tokyo").normalize().tz_localize(None)
    this_m = pd.Timestamp(today.year, today.month, 1)
    prev_m = this_m - pd.offsets.MonthBegin(1)
    prev2_m = this_m - pd.offsets.MonthBegin(2)
    return {
        "this": f"{this_m.month}月",
        "prev": f"{prev_m.month}月",
        "prev2": f"{prev2_m.month}月",
        # raw timestamps too
        "_this_ts": this_m,
        "_prev_ts": prev_m,
        "_prev2_ts": prev2_m,
    }


def load_op_receive_rate(coupon: str | None = None) -> pd.DataFrame:
    master = load_subscription_master().copy()
    master = _apply_coupon_filter(master, coupon)
    master["成約日"] = pd.to_datetime(master["成約日"])
    ship = _shipped_count_per_master()
    df = master.merge(ship, on="マスタID", how="left")
    df["shipped_count"] = df["shipped_count"].fillna(0).astype(int)
    df["has_received"] = (df["shipped_count"] >= 1).astype(int)
    df["month"] = df["成約日"].dt.to_period("M").dt.to_timestamp()

    labels = recent_month_labels()
    this_m, prev_m, prev2_m = labels["_this_ts"], labels["_prev_ts"], labels["_prev2_ts"]

    in_window = df[df["month"].isin([this_m, prev_m, prev2_m])].copy()

    agg = (
        in_window.groupby(["担当者名", "month"])
        .agg(成約数=("マスタID", "nunique"), 初回受取数=("has_received", "sum"))
        .reset_index()
    )

    months_map = {prev2_m: labels["prev2"], prev_m: labels["prev"], this_m: labels["this"]}
    rows: list[dict] = []
    for op, g in agg.groupby("担当者名"):
        row: dict = {"OP名": op}
        for m_ts, label in months_map.items():
            sub = g[g["month"] == m_ts]
            if sub.empty:
                row[f"{label}_成約数"] = None
                row[f"{label}_初回受取数"] = None
                row[f"{label}_初回受取率"] = None
            else:
                seiyaku = int(sub["成約数"].iloc[0])
                uketori = int(sub["初回受取数"].iloc[0])
                row[f"{label}_成約数"] = seiyaku
                row[f"{label}_初回受取数"] = uketori
                row[f"{label}_初回受取率"] = (uketori / seiyaku) if seiyaku else None
        rows.append(row)
    out = pd.DataFrame(rows)
    cols = ["OP名"]
    # 表示順: 当月→前月→前々月（直近を左に）
    for key in ["this", "prev", "prev2"]:
        label = labels[key]
        cols += [f"{label}_成約数", f"{label}_初回受取数", f"{label}_初回受取率"]
    return out[cols].sort_values("OP名").reset_index(drop=True)


def load_daily_op_receive_rate(coupon: str | None = None) -> pd.DataFrame:
    """成約日 × OP の 成約数 / 初回受取数 / 初回受取率。

    初回受取率 = 当該成約日の成約のうち、発送完了（対応状況=5）が
    21日以上前に1件以上記録された割合。21日未経過の日は0%付近に
    出やすいので注意。
    """
    master = load_subscription_master().copy()
    master = _apply_coupon_filter(master, coupon)
    master["成約日"] = pd.to_datetime(master["成約日"])
    ship = _shipped_count_per_master()
    df = master.merge(ship, on="マスタID", how="left")
    df["shipped_count"] = df["shipped_count"].fillna(0).astype(int)
    df["has_received"] = (df["shipped_count"] >= 1).astype(int)
    df = df.dropna(subset=["成約日", "担当者名"])

    agg = (
        df.groupby(["企業名", "担当者名", "成約日"])
        .agg(成約数=("マスタID", "nunique"), 初回受取数=("has_received", "sum"))
        .reset_index()
    )
    agg["初回受取率"] = agg.apply(
        lambda r: (r["初回受取数"] / r["成約数"]) if r["成約数"] else None,
        axis=1,
    )

    today = pd.Timestamp.now(tz="Asia/Tokyo").normalize().tz_localize(None)
    maturity_cutoff = today - pd.Timedelta(days=21)
    agg["成熟"] = agg["成約日"] <= maturity_cutoff

    return agg.rename(columns={"担当者名": "OP名"})


def load_monthly_op_receive_rate(coupon: str | None = None) -> pd.DataFrame:
    """月 × OP の 成約数 / 初回受取数 / 初回受取率。

    OP別デイリー受取率の月集計版。全期間の月別履歴を返す。
    """
    master = load_subscription_master().copy()
    master = _apply_coupon_filter(master, coupon)
    master["成約日"] = pd.to_datetime(master["成約日"])
    ship = _shipped_count_per_master()
    df = master.merge(ship, on="マスタID", how="left")
    df["shipped_count"] = df["shipped_count"].fillna(0).astype(int)
    df["has_received"] = (df["shipped_count"] >= 1).astype(int)
    df["月"] = df["成約日"].dt.to_period("M").dt.to_timestamp()
    df = df.dropna(subset=["月", "担当者名", "企業名"])

    agg = (
        df.groupby(["企業名", "担当者名", "月"])
        .agg(成約数=("マスタID", "nunique"), 初回受取数=("has_received", "sum"))
        .reset_index()
    )
    agg["初回受取率"] = agg.apply(
        lambda r: (r["初回受取数"] / r["成約数"]) if r["成約数"] else None, axis=1
    )

    today = pd.Timestamp.now(tz="Asia/Tokyo").normalize().tz_localize(None)
    # 月単位の成熟: 当月は21日経過してない可能性が高いので未成熟扱い
    this_month_start = pd.Timestamp(today.year, today.month, 1)
    agg["成熟"] = agg["月"] < this_month_start

    return agg.rename(columns={"担当者名": "OP名"})


def load_retention() -> pd.DataFrame:
    master = load_subscription_master().copy()
    master["成約日"] = pd.to_datetime(master["成約日"])
    ship = _shipped_count_per_master()
    df = master.merge(ship, on="マスタID", how="left")
    df["shipped_count"] = df["shipped_count"].fillna(0).astype(int)
    df["first_purchase_month"] = df["成約日"].dt.strftime("%Y-%m")
    df = df.dropna(subset=["first_purchase_month"])

    max_step = 16
    rows: list[dict] = []
    for month, g in df.groupby("first_purchase_month"):
        total = int(g["マスタID"].nunique())
        row: dict = {"first_purchase_month": month, "total_subscriptions": total}
        prev_cnt: int | None = None
        for n in range(1, max_step + 1):
            cnt = int((g["shipped_count"] >= n).sum())
            row[f"cnt_{n}"] = cnt
            if n == 1:
                rate = (cnt / total) if total else None
            else:
                rate = (cnt / prev_cnt) if prev_cnt else None
            row[f"rate_{n}"] = round(rate, 4) if rate is not None else None
            prev_cnt = cnt
        rows.append(row)
    return pd.DataFrame(rows).sort_values("first_purchase_month").reset_index(drop=True)
