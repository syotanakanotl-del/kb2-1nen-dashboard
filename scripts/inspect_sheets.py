"""Inspect actual sheet headers and BQ external table mapping."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.oauth2 import service_account
from googleapiclient.discovery import build

creds = service_account.Credentials.from_service_account_file(
    "secrets/dashboard-bq-key.json",
    scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
)
svc = build("sheets", "v4", credentials=creds, cache_discovery=False)

print("=== item_master sheet 'KB' row 1 ===")
res = svc.spreadsheets().values().get(
    spreadsheetId="1lrBYe5MLzXRp2IfE05GpRrycCzZy9tFEyY0itCaTjF4",
    range="KB!A1:Z1",
).execute()
header = res.get("values", [[]])[0]
for i, h in enumerate(header):
    print(f"  col{i:2d} ({chr(65+i)}): {h!r}")

print()
print("=== sample row from KB!A2:P2 ===")
res2 = svc.spreadsheets().values().get(
    spreadsheetId="1lrBYe5MLzXRp2IfE05GpRrycCzZy9tFEyY0itCaTjF4",
    range="KB!A2:P5",
).execute()
for r in res2.get("values", []):
    print(" ", r)

print()
print("=== subscription_master Ⅱ① first 3 rows ===")
res3 = svc.spreadsheets().values().get(
    spreadsheetId="1bRbSn6I8sa0C75h5zA8nQBfG9Lo3e39n_7ZkiLz2Ubw",
    range="キラーバーナーⅡ①!A1:E4",
).execute()
for r in res3.get("values", []):
    print(" ", r)
