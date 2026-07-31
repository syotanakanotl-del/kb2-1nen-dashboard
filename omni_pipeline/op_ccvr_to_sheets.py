# -*- coding: utf-8 -*-
"""OP(コール者)別 CCVR を月横並びでスプレッドシートに出す。
タブ = 商品 × {チャレF1, チャレF2, 集中F1, 合算F1, 合算F2}。コール月ベース。
各月ブロック = [コール者(履歴), CT数, CV数, CVR]、全体行を上に、CVR降順。
  CT数=コンタクト数, CV数=成約1年数, CVR=CV/CT。
"""
import sys, socket, time, datetime
socket.setdefaulttimeout(600)
sys.stdout.reconfigure(encoding="utf-8")
from google.oauth2.credentials import Credentials
from google.cloud import bigquery
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

TOKEN = r"C:\Users\syota\AppData\Roaming\gcloud\application_default_credentials.json"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform",
          "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
bq = bigquery.Client(project="trustline-project", credentials=creds, location="asia-northeast1")
sheets = build("sheets", "v4", credentials=creds)
drive = build("drive", "v3", credentials=creds)

BASE = "`trustline-project.omni_call_log.base_1nen_ob`"
SS_NAME = "1年OB・OP別CCVR"
BLOCK = ["コール者(履歴)", "CT数", "CV数", "CVR"]
BW = len(BLOCK)
GAP = 1
PROD_ORDER = ["キラDROP", "キラⅡ", "ペルル美容液"]
# (flabel, course_like(None=合算/全コース), tei)
VARIANTS = [
    ("チャレF1", "%チャレンジ%", 1),
    ("チャレF2", "%チャレンジ%", 2),
    ("集中F1",  "%集中%",      1),
    ("合算F1",  None,          1),
    ("合算F2",  None,          2),
]
TAB_COLORS = {
    "キラⅡ":      {"red": 1.0, "green": 0.65, "blue": 0.25},
    "キラDROP":    {"red": 1.0, "green": 0.60, "blue": 0.75},
    "ペルル美容液": {"red": 0.60, "green": 0.85, "blue": 1.0},
}


def col_letter(n):
    s = ""; n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def fetch(prod, course_like, tei):
    # tei=None なら定期購入回数で絞らない(全商材_チャレ/集中/合算=F1/F2区別なしの集計に使用)
    conds = ["DATE(`コール日時`) >= DATE '2025-11-01'",
             "`コール者` IS NOT NULL", "`コール者` != ''"]
    params = []
    if tei is not None:
        conds.append("`定期購入回数` = @tei")
        params.append(bigquery.ScalarQueryParameter("tei", "INT64", tei))
    if prod:   # 商材指定 / Noneなら3商材まとめ（合算）
        conds.append("SPLIT(`利用コース`,' ')[OFFSET(0)] = @prod")
        params.append(bigquery.ScalarQueryParameter("prod", "STRING", prod))
    else:
        conds.append("SPLIT(`利用コース`,' ')[OFFSET(0)] IN ('キラⅡ','キラDROP','ペルル美容液')")
    if course_like:
        conds.append("`利用コース` LIKE @course")
        params.append(bigquery.ScalarQueryParameter("course", "STRING", course_like))
    sql = f"""
    WITH x AS (
      SELECT FORMAT_DATE('%Y-%m', DATE(`コール日時`)) AS ym, `コール者` AS op,
             `コンタクト` AS ct_flag, `成約1年` AS cv_flag
      FROM {BASE} WHERE {' AND '.join(conds)}
    )
    SELECT ym, op, COUNTIF(ct_flag) AS ct, COUNTIF(cv_flag) AS cv
    FROM x GROUP BY ym, op
    """
    cfg = bigquery.QueryJobConfig(query_parameters=params)
    data = {}
    for r in bq.query(sql, job_config=cfg).result():
        data.setdefault(r.ym, []).append((r.op, r.ct, r.cv))
    return data


def cvr(cv, ct):
    return round(cv / ct, 4) if ct else 0


def build_grid(data, flabel):
    months = sorted(data.keys(), reverse=True)   # 左=最新月, 右=古い月
    for ym in months:
        data[ym].sort(key=lambda t: (cvr(t[2], t[1]), t[1]), reverse=True)
    maxops = max((len(v) for v in data.values()), default=0)
    nrow = 3 + maxops
    ncol = len(months) * (BW + GAP)
    grid = [["" for _ in range(ncol)] for _ in range(nrow)]
    for mi, ym in enumerate(months):
        c0 = mi * (BW + GAP)
        grid[0][c0] = f"{int(ym[5:7])}月{flabel}"
        for j, h in enumerate(BLOCK):
            grid[1][c0 + j] = h
        tct = sum(t[1] for t in data[ym]); tcv = sum(t[2] for t in data[ym])
        grid[2][c0:c0 + BW] = ["全体", tct, tcv, cvr(tcv, tct)]
        for k, (op, ct, cv) in enumerate(data[ym]):
            grid[3 + k][c0:c0 + BW] = [op, ct, cv, cvr(cv, ct)]
    return grid, ncol, len(months)


# --- OP別 一時間当たり 通話時間/コンタクト回数(全商品合算・日別・転置) ---
# 実働時間 = 架電があった時間帯(時間バケット=DATETIME_TRUNC(コール日時,HOUR))の数。
# 縦=日付 / 横=OP。最上部に「平均」行(期間通算=総通話秒÷総稼働h)。
#   通話時間タブ: 値=その日の 通話秒/稼働h を H:MM:SS 表示。
#   コンタクトタブ: 値=その日の ｺﾝﾀｸﾄ数/稼働h を小数表示。
TALK_START = datetime.date(2025, 11, 1)


def _hms(sec):
    sec = int(round(sec))
    h, r = divmod(sec, 3600); m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}"


def fetch_talk_daily():
    sql = f"""
    WITH x AS (
      SELECT DATE(`コール日時`) AS d, `コール者` AS op,
             DATETIME_TRUNC(DATETIME(`コール日時`), HOUR) AS hr,
             MAX(DATETIME(`コール日時`)) AS last_dt,   -- その時間枠の最終コール時刻
             -- 通話時間=コンタクトしたコール + 時間指定は全部(再架電可・放棄呼の未コンタクトは除外)
             SUM(IF(`コンタクト` OR `コール結果` = '時間指定', IFNULL(`通話秒数`, 0), 0)) AS talk,
             COUNTIF(`コンタクト`) AS ct
      FROM {BASE}
      WHERE DATE(`コール日時`) >= DATE '{TALK_START}'
        AND `コール者` IS NOT NULL AND `コール者` != ''
      GROUP BY 1,2,3
    )
    SELECT d, op,
           -- 稼働時間: 19時未満の枠=1.0h、19時以降の枠=最終コール時刻までの部分時間(区切る)
           SUM(IF(EXTRACT(HOUR FROM hr) < 19, 1.0,
                  DATETIME_DIFF(last_dt, hr, SECOND) / 3600.0)) AS ah,
           IFNULL(SUM(talk),0) AS talk, SUM(ct) AS ct
    FROM x GROUP BY d, op
    """
    cell = {}   # (op, d) -> (ah, talk, ct)
    tot = {}    # op -> [ah, talk, ct]
    dates = set()
    for r in bq.query(sql).result():
        cell[(r.op, r.d)] = (r.ah, r.talk or 0, r.ct or 0)
        t = tot.setdefault(r.op, [0, 0, 0])
        t[0] += r.ah; t[1] += (r.talk or 0); t[2] += (r.ct or 0)
        dates.add(r.d)
    return cell, tot, dates


_TALK_META = {}   # build_talk_daily が月平均行index・月グループ範囲を格納(書式ループで使用)


def build_talk_daily():
    """OP1人につき2列[通話時間(H:MM:SS), ｺﾝﾀｸﾄ/時]。縦=日付/横=OP。
    最上部に全体平均(黄)→各月[月平均行＋その月の日次行(月グループで折りたたみ可)]。"""
    cell, tot, dates = fetch_talk_daily()
    if not dates:
        return None
    ops = sorted(tot, key=lambda o: tot[o][0], reverse=True)  # 稼働時間の多い順=主力OPが左
    # 月別合計
    month_tot = {}
    for (op, d), (ah, talk, ct) in cell.items():
        t = month_tot.setdefault((op, (d.year, d.month)), [0, 0, 0])
        t[0] += ah; t[1] += talk; t[2] += ct
    dmin, dmax = min(dates), max(dates)
    all_dates = [dmin + datetime.timedelta(days=i) for i in range((dmax - dmin).days + 1)]

    def op_cells(getter):
        out = []
        for o in ops:
            v = getter(o)
            out += [_hms(v[1] / v[0]), round(v[2] / v[0], 2)] if (v and v[0]) else ["", ""]
        return out

    row_op = [""]; row_sub = [""]
    for o in ops:
        row_op += [o, ""]
        row_sub += ["通話時間", "ｺﾝﾀｸﾄ/時"]
    grid = [row_op, row_sub, ["平均"] + op_cells(lambda o: tot[o])]   # 行2=全体平均
    month_total_rows = []   # 月平均行のindex
    month_ranges = []       # 各月の日次行レンジ(行グループ用)
    months = sorted({(d.year, d.month) for d in all_dates})
    for (y, m) in months:
        month_total_rows.append(len(grid))
        grid.append([f"{y}年{m}月 平均"] + op_cells(lambda o: month_tot.get((o, (y, m)))))
        first = len(grid)
        for d in [dd for dd in all_dates if dd.year == y and dd.month == m]:
            grid.append([f"'{d.month}/{d.day}"] + op_cells(lambda o: cell.get((o, d))))
        if len(grid) > first:
            month_ranges.append((first, len(grid)))
    ncol = 1 + 2 * len(ops)   # 日付 + OP×2
    _TALK_META["month_total_rows"] = month_total_rows
    _TALK_META["month_ranges"] = month_ranges
    return grid, ncol, len(ops)


# --- OP別 日次CCVR (1年OB + 電話重複OB 合算・全商品・日別・転置) ---
# 縦=日付 / 横=OP(1人につき3列 [CT数, CV数, CVR])。日々のOP別CVRの変化を追う用途。
# データ = base_1nen_ob(成約1年) + base_denwacv(成約) を UNION。CMOB金子昌平を先頭固定。
# 最上部に「全体」行(期間通算 ΣCV/ΣCT)、続いて各月[月合計行＋その月の日次行(月グループで折りたたみ可)]。
# CT=コンタクト数, CV=成約数, CVR=CV/CT。両baseとも集計除外OP適用済み。
_CCVR_META = {}


DENWACV_BASE = "`trustline-project.omni_call_log.base_denwacv`"   # 電話重複CV OB
PIN_OP = "CMOB金子昌平"   # 日次CCVRタブで常に先頭(左端)に固定するOP


def fetch_ccvr_daily():
    # 1年OB(成約1年) + 電話重複OB(成約) を UNION して 日×コール者 で集計。
    # コール者名は両baseでほぼ一致(denwacv専用は極少)。同名OPは合算される。
    sql = f"""
    WITH u AS (
      SELECT DATE(`コール日時`) AS d, `コール者` AS op, `コンタクト` AS ct, `成約1年` AS cv
      FROM {BASE}
      WHERE DATE(`コール日時`) >= DATE '{TALK_START}' AND `コール者` IS NOT NULL AND `コール者` != ''
      UNION ALL
      SELECT DATE(`コール日時`) AS d, `コール者` AS op, `コンタクト` AS ct, `成約` AS cv
      FROM {DENWACV_BASE}
      WHERE DATE(`コール日時`) >= DATE '{TALK_START}' AND `コール者` IS NOT NULL AND `コール者` != ''
    )
    SELECT d, op, COUNTIF(ct) AS ct, COUNTIF(cv) AS cv
    FROM u GROUP BY d, op
    """
    cell = {}   # (op, d) -> (ct, cv)
    tot = {}    # op -> [ct, cv]
    dates = set()
    for r in bq.query(sql).result():
        cell[(r.op, r.d)] = (r.ct or 0, r.cv or 0)
        t = tot.setdefault(r.op, [0, 0]); t[0] += (r.ct or 0); t[1] += (r.cv or 0)
        dates.add(r.d)
    return cell, tot, dates


def build_ccvr_daily():
    """OP1人につき3列[CT数, CV数, CVR]。縦=日付/横=OP(全商品合算)。
    最上部に全体(黄, 期間通算ΣCV/ΣCT)→各月[月合計行(グレー)＋その月の日次行(月グループ折りたたみ可)]。"""
    cell, tot, dates = fetch_ccvr_daily()
    if not dates:
        return None
    ops = sorted(tot, key=lambda o: tot[o][0], reverse=True)  # 総CT多い順=主力OPが左
    if PIN_OP in ops:   # CMOB金子昌平 を常に先頭(左端)に固定
        ops = [PIN_OP] + [o for o in ops if o != PIN_OP]
    month_tot = {}
    for (op, d), (ct, cv) in cell.items():
        t = month_tot.setdefault((op, (d.year, d.month)), [0, 0]); t[0] += ct; t[1] += cv
    dmin, dmax = min(dates), max(dates)
    all_dates = [dmin + datetime.timedelta(days=i) for i in range((dmax - dmin).days + 1)]

    def op_cells(getter):
        # 先頭に「合計」(その行の全OP合算)ブロック → 続いて各OP
        tct = tcv = 0
        per = []
        for o in ops:
            v = getter(o)
            if v and (v[0] or v[1]):
                per += [v[0], v[1], (cvr(v[1], v[0]) if v[0] else "")]
                tct += v[0]; tcv += v[1]
            else:
                per += ["", "", ""]
        total = [tct, tcv, (cvr(tcv, tct) if tct else "")] if (tct or tcv) else ["", "", ""]
        return total + per

    row_op = [""]; row_sub = [""]
    for name in ["合計"] + ops:   # 先頭=合計、次にCMOB金子昌平…
        row_op += [name, "", ""]
        row_sub += ["CT数", "CV数", "CVR"]
    grid = [row_op, row_sub, ["全体"] + op_cells(lambda o: tot.get(o))]   # 行3=期間通算
    month_total_rows = []   # 月合計行のindex
    month_ranges = []       # 各月の日次行レンジ(行グループ用)
    months = sorted({(d.year, d.month) for d in all_dates})
    for (y, m) in months:
        month_total_rows.append(len(grid))
        grid.append([f"'{y}年{m}月"] + op_cells(lambda o: month_tot.get((o, (y, m)))))   # 先頭'でテキスト固定(日付誤変換防止)
        first = len(grid)
        for d in [dd for dd in all_dates if dd.year == y and dd.month == m]:
            grid.append([f"'{d.month}/{d.day}"] + op_cells(lambda o: cell.get((o, d))))
        if len(grid) > first:
            month_ranges.append((first, len(grid)))
    nblk = len(ops) + 1   # 合計 + 各OP
    ncol = 1 + 3 * nblk   # 日付 + (合計+OP)×3
    _CCVR_META["month_total_rows"] = month_total_rows
    _CCVR_META["month_ranges"] = month_ranges
    return grid, ncol, nblk


def ccvr_daily_fmt(sid, grid, ncol, nblk):
    """OP別CCVR_日次タブ(日付/OP×3列[CT数,CV数,CVR]・転置)の整形リクエスト列を返す。
    op_ccvr_to_sheets(1年OB) と op_ccvr_denwacv_to_sheets(電話重複CV) の両方で使う共有整形。
    _CCVR_META(直近の build_ccvr_daily が設定)から月合計行index・月レンジを読む。"""
    fmt = []
    nops = nblk
    for i in range(nops):
        c0 = 1 + 3 * i   # 各OPの先頭列(CT数)
        fmt.append({"mergeCells": {"mergeType": "MERGE_ALL", "range": {
            "sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
            "startColumnIndex": c0, "endColumnIndex": c0 + 3}}})   # OP名を3列マージ
        fmt.append({"repeatCell": {   # CVR列=パーセント
            "range": {"sheetId": sid, "startRowIndex": 2, "startColumnIndex": c0 + 2, "endColumnIndex": c0 + 3},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0.00%"}}},
            "fields": "userEnteredFormat.numberFormat"}})
    fmt.append({"repeatCell": {   # 見出し2行 中央太字
        "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 2},
        "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER", "textFormat": {"bold": True}}},
        "fields": "userEnteredFormat(horizontalAlignment,textFormat)"}})
    fmt.append({"repeatCell": {   # 全体行=黄色＋太字
        "range": {"sheetId": sid, "startRowIndex": 2, "endRowIndex": 3, "startColumnIndex": 0, "endColumnIndex": ncol},
        "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1, "green": 1, "blue": 0.6}, "textFormat": {"bold": True}}},
        "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
    fmt.append({"updateSheetProperties": {"properties": {"sheetId": sid,   # 日付+合計列(3列)を固定
        "gridProperties": {"frozenColumnCount": 4}}, "fields": "gridProperties.frozenColumnCount"}})
    fmt.append({"repeatCell": {   # 全セル中央揃え
        "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": len(grid), "startColumnIndex": 0, "endColumnIndex": ncol},
        "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"}},
        "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment)"}})
    for ri in _CCVR_META.get("month_total_rows", []):   # 月合計行=太字+薄グレー
        fmt.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": ri, "endRowIndex": ri + 1, "startColumnIndex": 0, "endColumnIndex": ncol},
            "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}, "textFormat": {"bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
    mr = _CCVR_META.get("month_ranges", [])             # 月ごと日次行をグループ化。最新月以外は畳む
    for idx, (s, e) in enumerate(mr):
        rng = {"sheetId": sid, "dimension": "ROWS", "startIndex": s, "endIndex": e}
        fmt.append({"addDimensionGroup": {"range": rng}})
        collapsed = (idx != len(mr) - 1)   # 最後=最新月のみ展開
        fmt.append({"updateDimensionGroup": {"dimensionGroup": {"range": rng, "depth": 1, "collapsed": collapsed}, "fields": "collapsed"}})
    return fmt


# --- CVR分析: リード鮮度別 週次CVR (1年OB) ---
# 縦=週(月曜始まり) / 横=[全体CT, 全体CVR, 中央経過日, 鮮度帯(0-14/15-30/31-60/61+)ごとCT・CVR]。
# CVR低下が「鮮度ミックスの悪化(古いリード比率上昇)」か「帯内の地合い低下」かを切り分ける診断用。
# 経過日数 = コール日 − 初回注文日。中央経過日=コンタクトした行の中央値(=リストの古さの指標)。
def build_cvr_freshness(course_like=None):
    cond = f"AND `利用コース` LIKE '{course_like}'" if course_like else ""
    sql = f"""
    WITH x AS (
      SELECT DATE_TRUNC(DATE(`コール日時`), WEEK(MONDAY)) wk, `コンタクト` ct, `成約1年` cv,
             DATE_DIFF(DATE(`コール日時`), DATE(`初回注文日`), DAY) age
      FROM {BASE}
      WHERE DATE(`コール日時`) >= DATE '{TALK_START}'
        AND `コール者` IS NOT NULL AND `コール者` != '' AND `初回注文日` IS NOT NULL {cond}
    )
    SELECT wk, COUNTIF(ct) ct_all, COUNTIF(cv) cv_all,
      APPROX_QUANTILES(IF(ct, age, NULL), 2)[OFFSET(1)] med_age,
      COUNTIF(ct AND age <= 14) c1, COUNTIF(cv AND age <= 14) v1,
      COUNTIF(ct AND age BETWEEN 15 AND 30) c2, COUNTIF(cv AND age BETWEEN 15 AND 30) v2,
      COUNTIF(ct AND age BETWEEN 31 AND 60) c3, COUNTIF(cv AND age BETWEEN 31 AND 60) v3,
      COUNTIF(ct AND age >= 61) c4, COUNTIF(cv AND age >= 61) v4
    FROM x GROUP BY wk ORDER BY wk
    """
    rows = list(bq.query(sql).result())
    if not rows:
        return None
    header = ["週(月曜)", "全体CT", "全体CVR", "中央経過日",
              "0-14日CT", "0-14日CVR", "15-30日CT", "15-30日CVR",
              "31-60日CT", "31-60日CVR", "61日+CT", "61日+CVR"]
    grid = [header]
    for r in rows:
        grid.append([
            f"'{r.wk:%y/%m/%d}",
            r.ct_all, cvr(r.cv_all, r.ct_all), r.med_age,
            r.c1, (cvr(r.v1, r.c1) if r.c1 else ""),
            r.c2, (cvr(r.v2, r.c2) if r.c2 else ""),
            r.c3, (cvr(r.v3, r.c3) if r.c3 else ""),
            r.c4, (cvr(r.v4, r.c4) if r.c4 else ""),
        ])
    return grid, len(header)


def _trend_lines(wks):
    """鮮度別週次データ(grid[1:])から、直近傾向の4行+所見を方向つきで生成。"""
    if len(wks) < 2:
        return ["(データ不足)"]

    def wl(r):
        return (r[0] or "").lstrip("'")

    def nz(x):
        return x if isinstance(x, (int, float)) else 0

    def pctv(x):
        return f"{nz(x) * 100:.1f}%"

    def dcvr(new, old):
        d = (nz(new) - nz(old)) * 100
        return f"横ばい({d:+.1f}pp)" if abs(d) < 1 else ("上昇" if d > 0 else "低下") + f"({d:+.1f}pp)"

    def dct(new, old):
        n, o = nz(new), nz(old)
        if o == 0:
            return "-"
        p = (n - o) / o * 100
        return f"横ばい({p:+.0f}%)" if abs(p) < 10 else ("増加" if p > 0 else "減少") + f"({p:+.0f}%)"

    def dage(new, old):
        d = nz(new) - nz(old)
        return f"ほぼ横ばい({d:+.0f}日)" if abs(d) <= 3 else ("古く" if d > 0 else "新しく") + f"({d:+.0f}日)"

    L = wks[-1]
    M = wks[-5] if len(wks) >= 5 else wks[0]
    E = wks[-9] if len(wks) >= 9 else wks[0]
    cvr_d8 = (nz(L[2]) - nz(E[2])) * 100
    age_d8 = nz(L[3]) - nz(E[3])
    if cvr_d8 <= -2:
        note = "CVRは低下傾向。" + ("背景は中央経過日の上昇＝新鮮リードが減り古いリード中心の架電に(鮮度ミックス悪化)。"
                                     if age_d8 >= 5 else "鮮度は横ばいで、鮮度帯内CVR(地合い)の低下が中心。")
    elif cvr_d8 >= 2:
        note = "CVRは上昇・回復傾向。" + ("新鮮リード比率が戻り(中央経過日の低下)鮮度改善が寄与。" if age_d8 <= -5 else "")
    else:
        note = "CVRはおおむね横ばい。"
    return [
        f"CVR: 直近 {pctv(L[2])}({wl(L)}週) / 4週前 {pctv(M[2])} / 8週前 {pctv(E[2])} → 4週比 {dcvr(L[2], M[2])}、8週比 {dcvr(L[2], E[2])}",
        f"架電量(CT): 直近 {nz(L[1])}件 / 4週前 {nz(M[1])} / 8週前 {nz(E[1])} → 4週比 {dct(L[1], M[1])}",
        f"リード鮮度(中央経過日): 直近 {nz(L[3])}日 / 4週前 {nz(M[3])} / 8週前 {nz(E[3])} → 4週比 {dage(L[3], M[3])}",
        f"鮮度帯別 直近CVR(0-14/15-30/31-60/61+): {pctv(L[5])} / {pctv(L[7])} / {pctv(L[9])} / {pctv(L[11])}",
        f"所見: {note}",
    ]


def build_cvr_summary(sections):
    """直近の傾向分析を全体/チャレ/集中のセクション別に文章生成(1列テキスト)。
    sections=[(ラベル, 鮮度別grid), ...]。方向は毎朝データから自動判定＝陳腐化しない。"""
    if not sections:
        return None
    lines = ["【直近の傾向分析】 ※毎朝自動更新 / 1年OBベース(週次) / コース別"]
    for label, grid in sections:
        lines.append("")
        lines.append(f"━━━ {label} ━━━")
        lines += _trend_lines(grid[1:])
    lines += ["", "■ 根拠データ",
              "各タブ「CVR分析_リード鮮度別(_チャレ / _集中)」= 週次×鮮度帯(0-14/15-30/31-60/61日+)のCT・CVRと中央経過日。"]
    return [[t] for t in lines]


def find_or_create_ss(name):
    r = drive.files().list(
        q=f"name='{name}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
        fields="files(id)").execute()
    files = r.get("files", [])
    if files:
        ss_id = files[0]["id"]
        meta = sheets.spreadsheets().get(spreadsheetId=ss_id).execute()
        return ss_id, [s["properties"]["sheetId"] for s in meta["sheets"]]
    ss = sheets.spreadsheets().create(body={"properties": {"title": name}}).execute()
    return ss["spreadsheetId"], [s["properties"]["sheetId"] for s in ss["sheets"]]


def main():
    # 全タブ構築
    tabs = []   # (title, prod, grid, ncol, nmonths)
    # 全商材(3商材まとめ・全定期回数)×コース。電話重複CVシートと同形式(F1/F2区別なし)
    for title, flabel, course_like in [("全商材_チャレ", "チャレ", "%チャレンジ%"),
                                       ("全商材_集中", "集中", "%集中%"),
                                       ("全商材_合算", "合算", None)]:
        data = fetch(None, course_like, None)   # tei=None=全定期回数
        grid, ncol, nm = build_grid(data, flabel)
        if nm == 0:
            print(f"  skip(データなし): {title}")
            continue
        tabs.append((title, None, grid, ncol, nm, "ccvr"))
    # 先頭: 全商材合算（商材で分けない）タブ
    for flabel, course_like, tei in [("F1チャレ合算", "%チャレンジ%", 1),
                                     ("F2チャレ合算", "%チャレンジ%", 2),
                                     ("F1集中合算",  "%集中%",      1)]:
        data = fetch(None, course_like, tei)
        grid, ncol, nm = build_grid(data, flabel)
        if nm == 0:
            print(f"  skip(データなし): {flabel}")
            continue
        tabs.append((flabel, None, grid, ncol, nm, "ccvr"))   # prod=None=色なし
    # 商材別タブ
    for prod in PROD_ORDER:
        for flabel, course_like, tei in VARIANTS:
            data = fetch(prod, course_like, tei)
            grid, ncol, nm = build_grid(data, flabel)
            if nm == 0:
                print(f"  skip(データなし): {prod}_{flabel}")
                continue
            tabs.append((f"{prod}_{flabel}", prod, grid, ncol, nm, "ccvr"))
    # OP別 一時間当たり 通話時間/コンタクト(全商品合算・日別転置・OP×2列) を先頭タブに追加
    tres = build_talk_daily()
    if tres:
        tgrid, tncol, tnops = tres
        tabs.insert(0, ("OP別_通話コンタクト", None, tgrid, tncol, tnops, "talk2"))
    # OP別 日次CCVR(全商品合算・日別転置・OP×3列 [CT数,CV数,CVR]) を先頭タブに追加
    cres = build_ccvr_daily()
    if cres:
        cgrid, cncol, cnops = cres
        tabs.insert(0, ("OP別CCVR_日次", None, cgrid, cncol, cnops, "ccvr_daily"))
    # CVR分析: サマリー → リード鮮度別(全体/チャレ/集中)。順序=[..,サマリー,全体,チャレ,集中,..]
    base_pos = 1 if cres else 0
    fspecs = [(None, "リード鮮度別", "全体"),
              ("%チャレンジ%", "リード鮮度別_チャレ", "チャレ"),
              ("%集中%", "リード鮮度別_集中", "集中")]
    fgrids = []
    for like, tabname, lab in fspecs:
        res = build_cvr_freshness(like)
        if res:
            g, nc = res
            fgrids.append((tabname, lab, g, nc))
    if fgrids:
        insert_at = base_pos
        for tabname, lab, g, nc in fgrids:
            tabs.insert(insert_at, (f"CVR分析_{tabname}", None, g, nc, 0, "cvr_freshness"))
            insert_at += 1
        sgrid = build_cvr_summary([(lab, g) for _, lab, g, _ in fgrids])
        if sgrid:
            tabs.insert(base_pos, ("CVR分析_サマリー", None, sgrid, 1, 0, "cvr_summary"))
    print(f"対象タブ: {len(tabs)}")
    max_rows = max(len(t[2]) for t in tabs)

    ss_id, old_sids = find_or_create_ss(SS_NAME)
    # タブ作り直し（temp→全削除→新規→temp削除）
    r = sheets.spreadsheets().batchUpdate(spreadsheetId=ss_id, body={"requests": [
        {"addSheet": {"properties": {"title": "_tmp"}}}]}).execute()
    tmp_id = r["replies"][0]["addSheet"]["properties"]["sheetId"]
    if old_sids:
        sheets.spreadsheets().batchUpdate(spreadsheetId=ss_id, body={"requests": [
            {"deleteSheet": {"sheetId": s}} for s in old_sids]}).execute()
    add = [{"addSheet": {"properties": {
        "title": t[0],
        "gridProperties": {"rowCount": len(t[2]) + 5, "columnCount": max(t[3], 1),
                           "frozenRowCount": 3}}}} for t in tabs]
    res = sheets.spreadsheets().batchUpdate(spreadsheetId=ss_id, body={"requests": add}).execute()
    title_to_id = {rp["addSheet"]["properties"]["title"]: rp["addSheet"]["properties"]["sheetId"]
                   for rp in res["replies"]}
    sheets.spreadsheets().batchUpdate(spreadsheetId=ss_id, body={"requests": [
        {"deleteSheet": {"sheetId": tmp_id}}]}).execute()

    fmt = []
    for title, prod, grid, ncol, nm, kind in tabs:
        sheets.spreadsheets().values().update(
            spreadsheetId=ss_id, range=f"'{title}'!A1",
            valueInputOption="USER_ENTERED", body={"values": grid}).execute()
        sid = title_to_id[title]
        if kind == "cvr_summary":   # 分析の結論・根拠(1列テキスト)。列幅広め+折返し、見出し太字
            fmt.append({"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 1050}, "fields": "pixelSize"}})
            fmt.append({"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": len(grid), "startColumnIndex": 0, "endColumnIndex": 1},
                "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "TOP", "horizontalAlignment": "LEFT"}},
                "fields": "userEnteredFormat(wrapStrategy,verticalAlignment,horizontalAlignment)"}})
            for ri, row in enumerate(grid):
                t = row[0] if row else ""
                if t.startswith("【") or t.startswith("■") or t.startswith("━"):
                    fmt.append({"repeatCell": {
                        "range": {"sheetId": sid, "startRowIndex": ri, "endRowIndex": ri + 1, "startColumnIndex": 0, "endColumnIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": (12 if t.startswith("【") else 11)}}},
                        "fields": "userEnteredFormat.textFormat"}})
            fmt.append({"updateSheetProperties": {"properties": {"sheetId": sid,
                "gridProperties": {"frozenRowCount": 0}}, "fields": "gridProperties.frozenRowCount"}})
            print(f"  書込: {title} ({len(grid)}行)")
            continue
        if kind == "cvr_freshness":   # 週次 / 鮮度帯別CVR。CVR列=%、見出し太字、週列固定
            for cc in (2, 5, 7, 9, 11):   # 全体CVR + 各鮮度帯CVR列
                fmt.append({"repeatCell": {
                    "range": {"sheetId": sid, "startRowIndex": 1, "startColumnIndex": cc, "endColumnIndex": cc + 1},
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0.00%"}}},
                    "fields": "userEnteredFormat.numberFormat"}})
            fmt.append({"repeatCell": {   # 見出し行 中央太字+薄グレー
                "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": ncol},
                "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER", "textFormat": {"bold": True},
                                               "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}}},
                "fields": "userEnteredFormat(horizontalAlignment,textFormat,backgroundColor)"}})
            fmt.append({"repeatCell": {   # 全セル中央揃え
                "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": len(grid), "startColumnIndex": 0, "endColumnIndex": ncol},
                "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"}},
                "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment)"}})
            fmt.append({"updateSheetProperties": {"properties": {"sheetId": sid,   # 週列(A)を固定
                "gridProperties": {"frozenColumnCount": 1, "frozenRowCount": 1}}, "fields": "gridProperties(frozenColumnCount,frozenRowCount)"}})
            print(f"  書込: {title} ({len(grid)}行=週)")
            continue
        if kind == "ccvr_daily":   # 日付 / OP×3列[CT数, CV数, CVR]、全体行(行2)黄色
            fmt += ccvr_daily_fmt(sid, grid, ncol, nm)
            print(f"  書込: {title} ({len(grid)}行 / 合計+OP{nm - 1}×3列 / 月{len(_CCVR_META.get('month_ranges', []))})")
            continue
        if kind == "talk2":   # 日付 / OP×2列[通話時間 H:MM:SS, ｺﾝﾀｸﾄ/時]、平均行(行2)黄色
            nops = nm
            for i in range(nops):
                c0 = 1 + 2 * i   # 各OPの先頭列(通話時間)
                fmt.append({"mergeCells": {"mergeType": "MERGE_ALL", "range": {
                    "sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                    "startColumnIndex": c0, "endColumnIndex": c0 + 2}}})   # OP名を2列マージ
                fmt.append({"repeatCell": {
                    "range": {"sheetId": sid, "startRowIndex": 2, "startColumnIndex": c0, "endColumnIndex": c0 + 1},
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "TIME", "pattern": "[h]:mm:ss"}}},
                    "fields": "userEnteredFormat.numberFormat"}})
                fmt.append({"repeatCell": {
                    "range": {"sheetId": sid, "startRowIndex": 2, "startColumnIndex": c0 + 1, "endColumnIndex": c0 + 2},
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0.00"}}},
                    "fields": "userEnteredFormat.numberFormat"}})
            fmt.append({"repeatCell": {   # 見出し2行 中央太字
                "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 2},
                "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER", "textFormat": {"bold": True}}},
                "fields": "userEnteredFormat(horizontalAlignment,textFormat)"}})
            fmt.append({"repeatCell": {   # 平均行=黄色＋太字
                "range": {"sheetId": sid, "startRowIndex": 2, "endRowIndex": 3, "startColumnIndex": 0, "endColumnIndex": ncol},
                "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1, "green": 1, "blue": 0.6}, "textFormat": {"bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
            fmt.append({"updateSheetProperties": {"properties": {"sheetId": sid,   # 日付を固定
                "gridProperties": {"frozenColumnCount": 1}}, "fields": "gridProperties.frozenColumnCount"}})
            fmt.append({"repeatCell": {   # 全セル中央揃え
                "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": len(grid), "startColumnIndex": 0, "endColumnIndex": ncol},
                "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"}},
                "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment)"}})
            for ri in _TALK_META.get("month_total_rows", []):   # 月平均行=太字+薄グレー
                fmt.append({"repeatCell": {
                    "range": {"sheetId": sid, "startRowIndex": ri, "endRowIndex": ri + 1, "startColumnIndex": 0, "endColumnIndex": ncol},
                    "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}, "textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
            mr = _TALK_META.get("month_ranges", [])             # 月ごと日次行をグループ化。最新月以外は畳む
            for idx, (s, e) in enumerate(mr):
                rng = {"sheetId": sid, "dimension": "ROWS", "startIndex": s, "endIndex": e}
                fmt.append({"addDimensionGroup": {"range": rng}})
                collapsed = (idx != len(mr) - 1)   # 最後=最新月のみ展開
                fmt.append({"updateDimensionGroup": {"dimensionGroup": {"range": rng, "depth": 1, "collapsed": collapsed}, "fields": "collapsed"}})
            print(f"  書込: {title} ({len(grid)}行 / OP{nm}×2列 / 月{len(mr)})")
            continue
        for mi in range(nm):   # CCVR: 月ブロック
            c0 = mi * (BW + GAP)
            fmt.append({"mergeCells": {"mergeType": "MERGE_ALL", "range": {
                "sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": c0, "endColumnIndex": c0 + BW}}})
            cc = c0 + 3
            fmt.append({"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": 2, "startColumnIndex": cc, "endColumnIndex": cc + 1},
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0.00%"}}},
                "fields": "userEnteredFormat.numberFormat"}})
        fmt.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 3},
            "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER", "textFormat": {"bold": True}}},
            "fields": "userEnteredFormat(horizontalAlignment,textFormat)"}})
        if prod in TAB_COLORS:
            fmt.append({"updateSheetProperties": {
                "properties": {"sheetId": sid, "tabColor": TAB_COLORS[prod]}, "fields": "tabColor"}})
        print(f"  書込: {title} ({len(grid)}行 / {nm}月)")

    for i in range(0, len(fmt), 100):
        for attempt in range(5):
            try:
                sheets.spreadsheets().batchUpdate(spreadsheetId=ss_id, body={"requests": fmt[i:i+100]}).execute()
                break
            except (TimeoutError, OSError, HttpError) as e:
                st = getattr(getattr(e, "resp", None), "status", None)
                if isinstance(e, HttpError) and st not in (429, 500, 503):
                    raise
                if attempt == 4:
                    raise
                time.sleep(5 * (attempt + 1))

    print("完了:", f"https://docs.google.com/spreadsheets/d/{ss_id}/edit")


if __name__ == "__main__":
    main()
