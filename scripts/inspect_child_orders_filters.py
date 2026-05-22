"""各データセットのchild_ordersビューSQLからretention_extractフィルタを抽出."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.bq import PROJECT_ID, get_bq_client
from lib.datasets import list_analyzable_datasets, parse_dataset_id

client = get_bq_client()

results = []
for dataset_id in list_analyzable_datasets():
    prod, plan = parse_dataset_id(dataset_id)
    try:
        table = client.get_table(f"{PROJECT_ID}.{dataset_id}.child_orders")
        sql = table.view_query or ""
        m = re.search(r"retention_extract[^']*'([^']+)'", sql)
        prefix = m.group(1) if m else "(NOT FOUND)"
        results.append((dataset_id, prod, plan, prefix))
    except Exception as e:
        results.append((dataset_id, prod, plan, f"ERROR: {type(e).__name__}"))

print(f"{'dataset':<30} {'prod':<5} {'plan':<15} retention_extract filter")
print("-" * 90)
for dataset_id, prod, plan, prefix in results:
    print(f"{dataset_id:<30} {prod or '?':<5} {plan or '?':<15} {prefix}")

# 集計: plan → prefix
print()
print("=== plan → retention_extract prefix（plan単位の集約） ===")
plan_to_prefixes: dict[str, set] = {}
for _, _, plan, prefix in results:
    if plan and not prefix.startswith("ERROR"):
        plan_to_prefixes.setdefault(plan, set()).add(prefix)
for plan, prefixes in sorted(plan_to_prefixes.items()):
    print(f"  {plan:<15} → {sorted(prefixes)}")
