"""What can the current ADC user query?"""
from google.cloud import bigquery

client = bigquery.Client(project="trustline-project")

queries = {
    "simple": "SELECT 1 AS n",
    "child_orders (view)": "SELECT COUNT(*) AS n FROM `trustline-project.KB2_1nen.child_orders`",
    "child_orders raw": "SELECT COUNT(*) AS n FROM `trustline-project.raw_keizoku_child_orders.KB_child_orders`",
    "item_master": "SELECT COUNT(*) AS n FROM `trustline-project.item_master.KB_item_master_full`",
    "retention_view": "SELECT COUNT(*) AS n FROM `trustline-project.KB2_1nen.KB2_1年継続率`",
}

for label, sql in queries.items():
    try:
        rows = list(client.query(sql).result())
        print(f"  [OK]   {label}: n={rows[0].n}")
    except Exception as e:
        msg = str(e).replace("\n", " ")[:160]
        print(f"  [FAIL] {label}: {msg}")
