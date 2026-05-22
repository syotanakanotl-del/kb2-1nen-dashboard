"""Test SA can read both Google Sheets."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.bq import (
    load_child_orders_filtered,
    load_item_master,
    load_op_receive_rate,
    load_retention,
    load_subscription_master,
)

print("=== item_master ===")
items = load_item_master()
print(items.shape, list(items.columns)[:6])

print("=== subscription_master ===")
master = load_subscription_master()
print(master.shape, list(master.columns))
print(master.head(3).to_string(index=False))

print("=== child_orders (filtered) ===")
co = load_child_orders_filtered()
print(co.shape)

print("=== op receive rate ===")
op = load_op_receive_rate()
print(op.shape)
print(op.head(5).to_string(index=False))

print("=== retention ===")
ret = load_retention()
print(ret.shape, list(ret.columns)[:6])
print(ret.head(3).to_string(index=False))
