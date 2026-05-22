"""Add the dashboard-bq service account to the KB2_1nen dataset ACL."""
import json
import subprocess
import sys

SA = "dashboard-bq@trustline-project.iam.gserviceaccount.com"
DATASET = "trustline-project:KB2_1nen"

result = subprocess.run(
    ["bq.cmd", "show", "--format=prettyjson", DATASET],
    capture_output=True, text=True, encoding="utf-8", shell=True,
)
if result.returncode != 0:
    print("bq show failed:", result.stderr)
    sys.exit(1)

d = json.loads(result.stdout)
access = d["access"]
if any(a.get("userByEmail") == SA for a in access):
    print(f"SA {SA} already in ACL")
else:
    access.append({"role": "READER", "userByEmail": SA})

with open("scripts/_dataset_acl.json", "w", encoding="utf-8") as f:
    json.dump({"access": access}, f, ensure_ascii=False, indent=2)

print("Wrote scripts/_dataset_acl.json. Now run:")
print(f'  bq update --source scripts/_dataset_acl.json {DATASET}')
