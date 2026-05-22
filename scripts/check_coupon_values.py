"""subscription_master のクーポンユニーク値を確認."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.bq import classify_coupon, load_subscription_master

m = load_subscription_master()
counts = m["クーポン"].fillna("(null)").value_counts().head(30)
print("=== クーポン値 上位30 ===")
for v, c in counts.items():
    cls = classify_coupon(v)
    print(f"  {cls:2s} | {c:>8,} | {v!r}")
