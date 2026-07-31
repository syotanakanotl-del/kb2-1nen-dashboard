# -*- coding: utf-8 -*-
"""電話重複CVの土台ビュー + 不在数コホートマート(コホート軸=初回注文日、キー=注文ナンバー)を作成。
   CSV構造はプレプラと同一。商品=利用コース先頭語(キラⅡ/キラDROP/ペルル美容液/キラ)、コース=チャレ/集中。
   コンタクト/成約(=◎始まり)の判定は 1年OB/プレプラ/休眠と同じ。除外OP・アポ禁・転送は使用しない。
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
SRC=f"`{DS}.call_history_denwacv`"; V=f"`{DS}.base_denwacv`"
PRODS="('キラⅡ','キラDROP','ペルル美容液','キラ','ミカ','テナル','メンディー','ペルル')"

# base_denwacv: 商品/コース/コンタクト/成約 を付与。初回注文日は元列。
# テナント(trustingline/wellmedia)を跨いで同一注文ナンバーが重複するため(実測70件)、
# コンタクト系ウィンドウ・distinct集計は `注文キー`=テナント|注文ナンバー で分離する。
bq.query(f"""
CREATE OR REPLACE VIEW {V} AS
WITH used AS (
  SELECT *, SPLIT(`利用コース`,' ')[OFFSET(0)] AS `商品`,
    CASE WHEN `利用コース` LIKE '%チャレンジ%' THEN 'チャレ'
         WHEN `利用コース` LIKE '%集中%'     THEN '集中' ELSE '他' END AS `コース`,
    CONCAT(COALESCE(`テナント`,'trustingline'),'|',`注文ナンバー`) AS `注文キー`
  FROM {SRC}
  WHERE `コール結果` NOT LIKE '%アポ禁%' AND `コール結果` != '転送'
    -- 集計除外OP(リスト再構成アカウント/特定OP)。NULL安全・プレフィックス/全角スペース差異に耐える
    AND NOT COALESCE(`コール者` LIKE '%トラストライン株式会社%' OR `コール者` LIKE '%日沼駿'
      OR `コール者` LIKE '%萩谷ななみ' OR `コール者` LIKE '%湊%裕矢', FALSE)
),
w1 AS (SELECT *, MAX(IF(`コール結果`!='時間指定',`コール日時`,NULL)) OVER(PARTITION BY `注文キー`) `_最終非時間指定` FROM used),
w2 AS (SELECT *, MIN(IF(`コール結果`='時間指定' AND (`_最終非時間指定` IS NULL OR `コール日時`>`_最終非時間指定`),`コール日時`,NULL)) OVER(PARTITION BY `注文キー`) `_末尾時間指定の最初` FROM w1)
SELECT * EXCEPT(`_最終非時間指定`,`_末尾時間指定の最初`),
  CASE WHEN `コール結果` IN ('再架電可','放棄呼') THEN FALSE
       WHEN `コール結果`='時間指定' THEN (`コール日時`=`_末尾時間指定の最初`)
       ELSE TRUE END AS `コンタクト`,
  STARTS_WITH(`コール結果`,'◎') AS `成約`
FROM w2
""").result()
print("✓ view:", V)

# 不在数(初回注文日コホート)。1年OB/休眠の mart と同ロジック。初回注文日NULL除外。
COMMON=f"""
WITH b AS (
  SELECT * FROM {V} WHERE `初回注文日` IS NOT NULL AND `商品` IN {PRODS}
),
seq AS (
  SELECT *, IFNULL(SUM(IF(`コール結果`='再架電可',1,0)) OVER (
    PARTITION BY `注文キー`
    ORDER BY `コール日時` ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0) AS `不在数`
  FROM b
)
"""
SEL="""COUNT(DISTINCT `注文キー`) `架電リスト数`, COUNT(*) `架電数`,
  COUNT(DISTINCT IF(`コンタクト`,`注文キー`,NULL)) `コンタクト数`,
  COUNT(DISTINCT IF(`成約`,`注文キー`,NULL)) `成約数`"""
for name, extra_g, extra_c in [
    ("mart_denwacv_absence", "", ""),
    ("mart_denwacv_absence_course", ",`コース`", ",`コース`"),
]:
    bq.query(f"""CREATE OR REPLACE VIEW `{DS}.{name}` AS {COMMON}
      SELECT `初回注文日`,`商品`{extra_c}, `不在数`, {SEL}
      FROM seq GROUP BY 1,2{extra_g},`不在数`""").result()
    print("✓ view:", name)
for name, extra_g, extra_c in [
    ("mart_denwacv_total", "", ""),
    ("mart_denwacv_total_course", ",`コース`", ",`コース`"),
]:
    bq.query(f"""CREATE OR REPLACE VIEW `{DS}.{name}` AS {COMMON}
      SELECT `初回注文日`,`商品`{extra_c}, {SEL}
      FROM seq GROUP BY 1,2{extra_g}""").result()
    print("✓ view:", name)

# 確認
print("\n=== base_denwacv 商品×コース ===")
for r in bq.query(f"""SELECT `商品`,`コース`, COUNT(*) n, COUNT(DISTINCT `注文ナンバー`) o,
  COUNTIF(`コンタクト`) ct, COUNTIF(`成約`) cv FROM {V}
  WHERE `初回注文日` IS NOT NULL GROUP BY 1,2 ORDER BY 3 DESC""").result():
    print(f"  {r.商品}/{r.コース}: {r.n}行 {r.o}注文 CT={r.ct} CV={r.cv}")
