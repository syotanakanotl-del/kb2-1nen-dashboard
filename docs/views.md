# BigQuery ビュー仕様 — `trustline-project.KB2_1nen`

KB2 1年定期購入のダッシュボード用ビュー一覧。

## 1. `subscription_master_KB2_1nen` — 成約マスタ

| カラム | 型 | 説明 |
|---|---|---|
| `成約日` | DATE | 成約日 |
| `マスタID` | INTEGER | 成約マスタID (一意) |
| `クーポン` | STRING | 適用クーポン |
| `企業名` | STRING | 企業名 |
| `担当者名` | STRING | OP（オペレーター）名 |
| `source_tab` | STRING | 元シート識別子 (KB2 1年OB キラーバーナーII①〜⑪) |

**ソース**: `_subscription_master_p1` 〜 `_p11` (Google Sheets 外部表) の UNION ALL。

## 2. `child_orders` — 子注文（発送実績）

| カラム | 型 | 説明 |
|---|---|---|
| `定期購入_マスター_受注ID` | INTEGER | 成約マスタIDに対応 |
| `定期購入_自動受注_回数` | INTEGER | 何回目の自動受注か |
| `発送日` | TIMESTAMP | 発送日時 |
| `支払い方法` | STRING | 決済手段 |
| `対応状況` | INTEGER | `5` = 配送完了（受取） |
| `注文ID` | INTEGER | 注文ID |
| `商品コード` | STRING | 商品コード |
| `定期初回注文日時` | TIMESTAMP | 定期初回注文日時 |

**フィルタ条件**: `item_master.KB_item_master_full` の `retention_extract LIKE '1年%'` の商品のみ。

## 3. `mart_op_receive_rate_kb2_1year` — OP別受取率（業務レポートのコア）

| カラム | 型 | 説明 |
|---|---|---|
| `OP名` | STRING | オペレーター名 |
| `当月_成約数` | INTEGER | 当月の成約マスタ数 |
| `当月_受取数` | INTEGER | 当月成約のうち初回受取済 |
| `当月_受取率` | FLOAT | 受取数 / 成約数 |
| `前月_成約数` 〜 `前月_受取率` | — | 前月の同指標 |
| `前々月_成約数` 〜 `前々月_受取率` | — | 前々月の同指標 |

**「受取済」の定義**: `対応状況 = 5` かつ `発送日 <= 21日前` の子注文が1件以上ある。

## 4. `KB2_1年継続率` — コホート別継続率

| カラム | 型 | 説明 |
|---|---|---|
| `first_purchase_month` | STRING | 成約月 (YYYY-MM) |
| `total_subscriptions` | INTEGER | その月の総成約数 |
| `cnt_1` 〜 `cnt_16` | INTEGER | N回以上発送された人数 |
| `rate_1` | FLOAT | cnt_1 / total_subscriptions |
| `rate_2` 〜 `rate_16` | FLOAT | cnt_N / cnt_(N-1) ＝ ステップ間継続率 |

**用途**: 月別コホートで定期購入が何回目まで続いたかを追う。
