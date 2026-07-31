# -*- coding: utf-8 -*-
"""電話重複CV架電履歴を過去に遡ってDL+取込(初回投入)。
   extract_omni の期間DL(2日付引数)を月チャンクで回し、load_denwacv_to_bq で取込。
   取込は DATE(コール日時) 単位で冪等。落ちた月は日次リトライにフォールバック。
   使い方: python backfill_denwacv.py 2026-01-01 2026-07-13
"""
import sys, os, subprocess, calendar, datetime as dt
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
PY = r"C:\Users\syota\OneDrive\dashboard\.venv\Scripts\python.exe"
ENV = dict(os.environ, PYTHONUTF8="1", OMNI_HOST="trustingline",
           OMNI_TEMPLATE="電話重複CV集計", OMNI_OUT_PREFIX="denwacv",
           OMNI_CONDITION_TYPE="Wt02CallHistory.created",  # コール日で絞る(最終コール日時ではない)
           OMNI_HEADLESS="1", OMNI_DL_TIMEOUT_MS="300000")

def extract(a, b):
    r = subprocess.run([PY, "-u", os.path.join(HERE, "extract_omni.py"),
                        a.strftime("%Y%m%d"), b.strftime("%Y%m%d")], env=ENV)
    csv = os.path.join(HERE, "data", f"denwacv_{a:%Y%m%d}_{b:%Y%m%d}.csv")
    return csv if (r.returncode == 0 and os.path.exists(csv)) else None

def load(csv):
    r = subprocess.run([PY, "-u", os.path.join(HERE, "load_denwacv_to_bq.py"), csv], env=ENV)
    return r.returncode == 0

def do_month(y, m, start, end):
    a = max(dt.date(y, m, 1), start)
    b = min(dt.date(y, m, calendar.monthrange(y, m)[1]), end)
    print(f"=== 月チャンク {a} 〜 {b} ===")
    csv = extract(a, b)
    if csv and load(csv):
        try: os.remove(csv)
        except OSError: pass
        return True
    print(f"  !! 月チャンク失敗 → 日次リトライ {a}〜{b}")
    d = a
    while d <= b:
        c = extract(d, d)
        if c and load(c):
            try: os.remove(c)
            except OSError: pass
        else:
            print(f"    !! 日次も失敗 {d}")
        d += dt.timedelta(days=1)
    return True

def main():
    start = dt.datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    end = dt.datetime.strptime(sys.argv[2], "%Y-%m-%d").date()
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        do_month(y, m, start, end)
        m += 1
        if m > 12: y += 1; m = 1
    print("=== backfill 完了 ===")

if __name__ == "__main__":
    main()
