"""すべてのデータセットの subscription_master シートがSAでアクセス可能か確認."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from googleapiclient.errors import HttpError

from lib.bq import get_sheets_service, get_subscription_sheet_info
from lib.datasets import display_name, list_analyzable_datasets

svc = get_sheets_service()
ok_count = fail_count = 0
fail_details: list[tuple[str, str, str]] = []

for ds in list_analyzable_datasets():
    try:
        info = get_subscription_sheet_info(ds)
    except Exception as e:
        print(f"  [META]  {ds}: {type(e).__name__}: {str(e)[:80]}")
        fail_count += 1
        fail_details.append((ds, "(unknown)", f"meta-error: {e}"))
        continue
    sheet_id = info.get("sheet_id")
    if not sheet_id:
        print(f"  [NULL]  {ds}: no sheet_id")
        fail_count += 1
        fail_details.append((ds, "(none)", "no sheet_id"))
        continue
    try:
        # Test access by getting sheet metadata (no values)
        svc.spreadsheets().get(
            spreadsheetId=sheet_id, fields="properties.title"
        ).execute()
        ok_count += 1
        print(f"  [OK]    {ds} → {sheet_id}")
    except HttpError as e:
        status = e.resp.status if hasattr(e, "resp") else "?"
        print(f"  [{status}]  {ds} → {sheet_id}: {str(e)[:80]}")
        fail_count += 1
        fail_details.append((ds, sheet_id, str(e)[:80]))

print()
print(f"=== Summary: OK={ok_count}, FAIL={fail_count} ===")
if fail_details:
    print()
    print("=== Need sharing with dashboard-bq@trustline-project.iam.gserviceaccount.com ===")
    unique_sheets = {}
    for ds, sid, _ in fail_details:
        unique_sheets.setdefault(sid, []).append(ds)
    for sid, dss in unique_sheets.items():
        print(f"\n  Sheet: https://docs.google.com/spreadsheets/d/{sid}/edit")
        print(f"    Used by: {', '.join(dss)}")
