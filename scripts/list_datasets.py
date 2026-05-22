"""trustline-project 内のデータセット一覧を取得."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.bq import get_bq_client

client = get_bq_client()
print(f"=== Datasets in {client.project} ===")
for ds in client.list_datasets():
    print(f"  {ds.dataset_id}")
