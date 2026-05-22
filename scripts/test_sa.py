"""Test the service account: can it query KB2_1nen views?"""
import os
from google.cloud import bigquery
from google.oauth2 import service_account

KEY = "secrets/dashboard-bq-key.json"
PROJECT = "trustline-project"

creds = service_account.Credentials.from_service_account_file(
    KEY,
    scopes=[
        "https://www.googleapis.com/auth/cloud-platform",
        "https://www.googleapis.com/auth/drive.readonly",
    ],
)
print(f"SA: {creds.service_account_email}")

client = bigquery.Client(project=PROJECT, credentials=creds)

queries = {
    "simple": "SELECT 1 AS n",
    "subscription_master (Sheets)": "SELECT COUNT(*) AS n FROM `trustline-project.KB2_1nen.subscription_master_KB2_1nen`",
    "child_orders": "SELECT COUNT(*) AS n FROM `trustline-project.KB2_1nen.child_orders`",
    "op receive rate": "SELECT COUNT(*) AS n FROM `trustline-project.KB2_1nen.mart_op_receive_rate_kb2_1year`",
}

for label, sql in queries.items():
    try:
        rows = list(client.query(sql).result())
        print(f"  [OK] {label}: n={rows[0].n}")
    except Exception as e:
        print(f"  [FAIL] {label}: {type(e).__name__}: {str(e)[:200]}")
