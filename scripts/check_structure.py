"""いくつかのデータセットのビュー構造を確認."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.bq import get_bq_client

PROJECT = "trustline-project"
SAMPLES = [
    "KB2_1nen",       # 既存
    "KB2_premium",
    "KB_1nen",
    "OM_1nen",
    "TL_premium",
    "PSS_royal_OB",
]

client = get_bq_client()
for ds in SAMPLES:
    print(f"\n=== {ds} ===")
    try:
        tables = list(client.list_tables(f"{PROJECT}.{ds}"))
        for t in tables:
            print(f"  {t.table_type:8} | {t.table_id}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {str(e)[:100]}")
