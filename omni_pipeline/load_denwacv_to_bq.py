# -*- coding: utf-8 -*-
"""電話重複CVの架電結果CSV(テンプレ「電話重複CV集計」)を
   BigQuery `omni_call_log.call_history_denwacv` へ冪等取込。
   ※CSV列構成はプレプラと同一(14列・進捗度なし・注文ナンバー/初回注文日あり)。
   使い方: python load_denwacv_to_bq.py <csv>
"""
import sys, os, glob, tempfile
sys.stdout.reconfigure(encoding="utf-8")
from google.oauth2.credentials import Credentials
from google.cloud import bigquery

PROJECT = "trustline-project"; DATASET = "omni_call_log"; LOCATION = "asia-northeast1"
TABLE = "call_history_denwacv"; STG_TABLE = "call_history_denwacv_stg"
TOKEN = r"C:\Users\syota\AppData\Roaming\gcloud\application_default_credentials.json"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform", "https://www.googleapis.com/auth/drive"]
SRC_ENCODING = "cp932"

# 電話重複CV CSVの列(ヘッダ順)。プレプラと同一14列。trustingline/wellmedia両テナントで同一。
COLUMNS = ["コール日時","コール開始日時","コール終了日時","通話秒数","呼出秒数","コール結果",
           "コール者","コールメモ","注文ナンバー","リスト名","利用コース","定期購入回数","初回注文日","INOUT"]

bq = bigquery.Client(project=PROJECT,
    credentials=Credentials.from_authorized_user_file(TOKEN, SCOPES), location=LOCATION)

def tenant_of(src):
    """取込テナント(trustingline/wellmedia)を決定。
    優先: 明示env OMNI_TENANT → extract時のOMNI_HOST → ファイル名(denwacvwm*/_wm)→ 既定trustingline。
    ※同一テーブルに両テナントが入るため、DELETE/INSERTはテナント単位でスコープする。"""
    t = os.environ.get("OMNI_TENANT") or os.environ.get("OMNI_HOST")
    if t:
        return t
    b = os.path.basename(src)
    return "wellmedia" if (b.startswith("denwacvwm") or "_wm" in b) else "trustingline"

def convert_to_utf8(src):
    fd, out = tempfile.mkstemp(suffix=".utf8.csv", prefix="denwacv_"); os.close(fd)
    n = 0
    with open(src, "r", encoding=SRC_ENCODING, errors="replace", newline="") as r, \
         open(out, "w", encoding="utf-8", newline="") as w:
        for line in r:
            w.write(line); n += 1
    print(f"  変換: {n:,} 行 → {out}")
    return out

def ensure_objects():
    bq.query(f"""CREATE TABLE IF NOT EXISTS `{PROJECT}.{DATASET}.{TABLE}` (
      `コール日時` TIMESTAMP, `注文ナンバー` STRING, `リスト名` STRING, `利用コース` STRING,
      `コール結果` STRING, `定期購入回数` INT64, `コール者` STRING, `初回注文日` DATE,
      `通話秒数` INT64, `INOUT` STRING, `取込ファイル` STRING, `取込日時` TIMESTAMP, `テナント` STRING)
    PARTITION BY DATE(`コール日時`)
    OPTIONS(description="電話重複CV OB架電履歴 日次取込(trustingline+wellmedia)")""").result()
    # 既存テーブルにテナント列が無い場合の後方互換(migrate漏れ対策)
    bq.query(f"ALTER TABLE `{PROJECT}.{DATASET}.{TABLE}` ADD COLUMN IF NOT EXISTS `テナント` STRING").result()

def load_staging(utf8_path):
    stg_id = f"{PROJECT}.{DATASET}.{STG_TABLE}"
    cfg = bigquery.LoadJobConfig(source_format=bigquery.SourceFormat.CSV, skip_leading_rows=1,
        encoding="UTF-8", quote_character='"', allow_quoted_newlines=True,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        schema=[bigquery.SchemaField(c, "STRING") for c in COLUMNS])
    with open(utf8_path, "rb") as f:
        bq.load_table_from_file(f, stg_id, job_config=cfg).result()
    n = bq.get_table(stg_id).num_rows
    print(f"  ステージング: {n:,} 行")
    return n

def merge(source_file, tenant):
    stg = f"`{PROJECT}.{DATASET}.{STG_TABLE}`"; tbl = f"`{PROJECT}.{DATASET}.{TABLE}`"
    typed = f"""
      SELECT SAFE.PARSE_TIMESTAMP('%Y-%m-%d %H:%M:%S', `コール日時`) AS `コール日時`,
        `注文ナンバー`, `リスト名`, `利用コース`, `コール結果`,
        SAFE_CAST(`定期購入回数` AS INT64) AS `定期購入回数`, `コール者`,
        COALESCE(SAFE.PARSE_DATE('%Y/%m/%d', `初回注文日`), SAFE.PARSE_DATE('%Y-%m-%d', `初回注文日`)) AS `初回注文日`,
        SAFE_CAST(`通話秒数` AS INT64) AS `通話秒数`, `INOUT`
      FROM {stg}"""
    params = [bigquery.ScalarQueryParameter("src", "STRING", source_file),
              bigquery.ScalarQueryParameter("tenant", "STRING", tenant)]
    # DELETEはテナント単位でスコープ(もう一方のテナントの同日行を消さない)
    d = bq.query(f"""DELETE FROM {tbl} WHERE `テナント`=@tenant AND DATE(`コール日時`) IN (
      SELECT DISTINCT DATE(`コール日時`) FROM ({typed}) WHERE `コール日時` IS NOT NULL)""",
      job_config=bigquery.QueryJobConfig(query_parameters=params))
    d.result(); print(f"  既存削除({tenant}・対象日): {d.num_dml_affected_rows:,} 行")
    ins = bq.query(f"""INSERT INTO {tbl}
      (`コール日時`,`注文ナンバー`,`リスト名`,`利用コース`,`コール結果`,`定期購入回数`,`コール者`,
       `初回注文日`,`通話秒数`,`INOUT`,`取込ファイル`,`取込日時`,`テナント`)
      SELECT t.*, @src AS `取込ファイル`, CURRENT_TIMESTAMP() AS `取込日時`, @tenant AS `テナント`
      FROM ({typed}) t WHERE t.`コール日時` IS NOT NULL""",
      job_config=bigquery.QueryJobConfig(query_parameters=params))
    ins.result(); print(f"  INSERT({tenant}): {ins.num_dml_affected_rows:,} 行")

def load_csv(src):
    tenant = tenant_of(src)
    print(f"=== 取込: {os.path.basename(src)} (テナント={tenant}) ===")
    u = convert_to_utf8(src)
    try:
        ensure_objects(); load_staging(u); merge(os.path.basename(src), tenant)
    finally:
        try: os.remove(u)
        except OSError: pass

if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else max(glob.glob(r"C:\Users\syota\OneDrive\dashboard\omni_pipeline\data\denwacv_*.csv"), key=os.path.getmtime)
    load_csv(p)
