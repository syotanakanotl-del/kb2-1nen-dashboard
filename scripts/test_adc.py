from google.cloud import bigquery

client = bigquery.Client(project="trustline-project")
sql = "SELECT COUNT(*) AS n FROM `trustline-project.KB2_1nen.subscription_master_KB2_1nen`"
try:
    rows = list(client.query(sql).result())
    print(f"OK: n={rows[0].n}")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
