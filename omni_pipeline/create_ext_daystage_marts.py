# -*- coding: utf-8 -*-
"""プレミアム/プラチナ/休眠の「対○○数コホート(経過日数=架電開始日基準)」マートを作成。
   1年OBの cohort_daystage と同形式だが、母数=コホート内distinct注文(外部新規数ではない)。
   - プレミアム: コホート日=date_1nen(1年4回目) / プラチナ: date_royal(ロイヤル4回目)  … base_prepla×prepla_first4_date
   - 休眠: コホート日=解約日  … base_dormant
   0日目=架電開始日=その日の架電リスト数(distinct)が母数の10%以上になった最初の暦日。早期分は0日目に合算。
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from google.oauth2.credentials import Credentials
from google.cloud import bigquery
bq=bigquery.Client(project="trustline-project",
  credentials=Credentials.from_authorized_user_file(
    r"C:\Users\syota\AppData\Roaming\gcloud\application_default_credentials.json",
    ["https://www.googleapis.com/auth/cloud-platform","https://www.googleapis.com/auth/drive"]),
  location="asia-northeast1")
DS="trustline-project.omni_call_log"
PRODS="('キラⅡ','キラDROP','ペルル美容液','キラ','ミカ','テナル','メンディー','ペルル')"
WINDOWS={"all":None,"w35":(0,35)}
def winagg():
    parts=[]
    for k,rng in WINDOWS.items():
        c="TRUE" if rng is None else f"(`経過日数` BETWEEN {rng[0]} AND {rng[1]})"
        parts.append(f"COUNTIF({c}) AS `{k}_コール数`")
        parts.append(f"COUNT(DISTINCT IF(`コンタクト` AND {c},`注文ナンバー`,NULL)) AS `{k}_コンタクト数`")
        parts.append(f"COUNT(DISTINCT IF(`成約` AND {c},`注文ナンバー`,NULL)) AS `{k}_成約数`")
    return ",\n  ".join(parts)

def _grain_sql(from_clause, prod_key, seg_expr, cohort_expr, where, final_win, order_key="bp.`注文ナンバー`"):
    """1グレイン分のSQL(reb CTEまで)を返す。prod_key/seg_exprに'合算'等のリテラルも可。
    order_key: distinct/母数のキー列式(既定=注文ナンバー)。電話重複CVはテナント跨ぎの
    同一注文ナンバー重複を分離するため `注文キー`(=テナント|注文ナンバー)を渡す。"""
    common=f"""
WITH b0 AS (
  SELECT {order_key} AS `注文ナンバー`, bp.`コール日時`, DATE(bp.`コール日時`) AS call_date,
    bp.`コンタクト`, bp.`成約`, {prod_key} AS `商品`, {seg_expr} AS seg, {cohort_expr} AS cohort_date
  FROM {from_clause}
  WHERE bp.`商品` IN {PRODS} {where}
),
b1 AS (SELECT * FROM b0 WHERE cohort_date IS NOT NULL AND seg IS NOT NULL),
mother AS (SELECT cohort_date,`商品`,seg, COUNT(DISTINCT `注文ナンバー`) bosu FROM b1 GROUP BY 1,2,3),
coh AS (SELECT b1.*, m.bosu FROM b1 JOIN mother m USING(cohort_date,`商品`,seg)),
daily AS (SELECT cohort_date,`商品`,seg,call_date, COUNT(DISTINCT `注文ナンバー`) day_list, ANY_VALUE(bosu) bosu FROM coh GROUP BY 1,2,3,4),
start AS (SELECT cohort_date,`商品`,seg, MIN(call_date) start_d FROM daily WHERE bosu>0 AND day_list>=bosu*0.10 GROUP BY 1,2,3),
reb AS (SELECT coh.*, s.start_d, GREATEST(0,DATE_DIFF(coh.call_date,s.start_d,DAY)) AS `経過日数` FROM coh JOIN start s USING(cohort_date,`商品`,seg))
"""
    if final_win:
        sel=f"""SELECT cohort_date AS `初回注文日`,`商品`,seg AS `コース`,
            ANY_VALUE(start_d) AS `架電開始日`, DATE_DIFF(ANY_VALUE(start_d),cohort_date,DAY) AS `架電開始offset`,
            ANY_VALUE(bosu) AS `母数`, COUNT(DISTINCT `注文ナンバー`) AS `架電リスト数`, {winagg()}
          FROM reb GROUP BY 1,2,3"""
    else:
        sel="""SELECT cohort_date AS `初回注文日`,`商品`,seg AS `コース`,`経過日数`,
            COUNT(DISTINCT `注文ナンバー`) AS `架電リスト数`, COUNT(*) AS `コール数`,
            COUNT(DISTINCT IF(`コンタクト`,`注文ナンバー`,NULL)) AS `コンタクト数`,
            COUNT(DISTINCT IF(`成約`,`注文ナンバー`,NULL)) AS `成約数`
          FROM reb WHERE `経過日数` BETWEEN 0 AND 35 GROUP BY 1,2,3,4"""
    return common+sel

def build(prefix, from_clause, grains, cohort_expr, where, order_key="bp.`注文ナンバー`"):
    """grains: [(prod_key, seg_expr), ...] を UNION ALL。商品別と合算を両方入れる。
    order_key: distinct/母数キー列式(既定=注文ナンバー)。"""
    for suffix, final_win in [("window",True),("day",False)]:
        union=" UNION ALL ".join(f"({_grain_sql(from_clause,pk,se,cohort_expr,where,final_win,order_key)})" for pk,se in grains)
        bq.query(f"CREATE OR REPLACE VIEW `{DS}.{prefix}_{suffix}` AS {union}").result()
        print("✓",f"{prefix}_{suffix}")

# プレプラ: 商品別(商品,プラン) + 合算(合算,プラン)。cohort=プラン別4回受取日
build("mart_ds_prepla",
      f"`{DS}.base_prepla` bp JOIN `{DS}.prepla_first4_date` m ON TRIM(bp.`注文ナンバー`)=m.`注文ナンバー`",
      [("bp.`商品`","bp.`プラン`"), ("'合算'","bp.`プラン`")],
      "IF(bp.`プラン`='プレミアム', m.date_1nen, m.date_royal)",
      "AND bp.`プラン` IN ('プレミアム','プラチナ') AND bp.`投入` IN ('初回','複数回')")
# 休眠: 商品×コース + 商品×合算。cohort=解約日
build("mart_ds_dormant",
      f"`{DS}.base_dormant` bp",
      [("bp.`商品`","bp.`コース`"), ("bp.`商品`","'合算'")],
      "bp.`解約日`",
      "AND bp.`解約日` IS NOT NULL AND bp.`コース` IN ('チャレ','集中')")
# かご落ち: 商品別(seg='合算') + 全商材合算。cohort=離脱日(かご落ち発生日)。キー=注文ナンバー(=電話番号 in base_kagoochi)
build("mart_ds_kagoochi",
      f"`{DS}.base_kagoochi` bp",
      [("bp.`商品`","'合算'"), ("'合算'","'合算'")],
      "bp.`離脱日`",
      "AND bp.`離脱日` IS NOT NULL")
# 電話重複CV: 商品×コース + 商品×合算。cohort=初回注文日。母数=コホート内distinct注文
# テナント跨ぎ重複を分離するため order_key=注文キー(テナント|注文ナンバー)
build("mart_ds_denwacv",
      f"`{DS}.base_denwacv` bp",
      [("bp.`商品`","bp.`コース`"), ("bp.`商品`","'合算'")],
      "bp.`初回注文日`",
      "AND bp.`初回注文日` IS NOT NULL AND bp.`コース` IN ('チャレ','集中')",
      order_key="bp.`注文キー`")

# 確認
print("\n=== プレプラ 母数(月別×プラン) ===")
for r in bq.query(f"""SELECT FORMAT_DATE('%Y-%m',`初回注文日`) ym,`コース` plan, SUM(`母数`) bosu
  FROM `{DS}.mart_ds_prepla_window` GROUP BY 1,2 ORDER BY 1,2""").result():
    print(f"  {r.ym} {r.plan}: 母数{r.bosu}")
