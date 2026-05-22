# KB2 1年定期ダッシュボード

`trustline-project.KB2_1nen` のビューを使ったStreamlitダッシュボード。

## 起動

```powershell
$env:Path = "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin;$env:Path"
.\.venv\Scripts\streamlit.exe run app.py
```

ブラウザで `http://localhost:8501` を開く。

## 前提

1. **gcloud SDK 認証済み**
   ```powershell
   gcloud auth application-default login
   ```
2. **BigQuery 権限**: `trustline-project` の `KB2_1nen` データセットに対する `bigquery.dataViewer` + `bigquery.jobUser`

## ページ構成

- **サマリー** (`app.py`): 当月KPI、月別推移、3ヶ月比較
- **OP別パフォーマンス** (`pages/1_OP別パフォーマンス.py`): 担当者別の表・棒グラフ・バブルチャート・3ヶ月推移
- **継続率** (`pages/2_継続率.py`): コホート別ステップ間 / 累積継続率
- **詳細データ** (`pages/3_詳細データ.py`): subscription_master をフィルタ＆CSVエクスポート

## キャッシュ

BigQueryクエリは Streamlit の `@st.cache_data(ttl=30分)` でキャッシュ。サイドバーの「キャッシュをクリア」で即時再取得。

## ファイル

- `app.py` — エントリポイント (サマリー)
- `pages/` — マルチページ
- `lib/bq.py` — BigQueryクライアント + クエリ
- `docs/views.md` — ビュー仕様
- `docs/dashboard_design.md` — 設計書
- `requirements.txt` — Python依存
