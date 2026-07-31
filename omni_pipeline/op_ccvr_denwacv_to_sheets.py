# -*- coding: utf-8 -*-
"""電話重複CV の OP別CCVR を月横並びでスプシ出力(コール月ベース、左=最新月)。
   タブ = {全商材合算, 商材別} × {チャレ, 集中, 合算}。各月ブロック=[コール者, CT数, CV数, CVR]。
   CT=コンタクト数, CV=成約数(◎), CVR=CV/CT。1年OB/プレプラ/休眠/かご落ちのOP別CCVRと同形。
"""
import sys, socket, time
socket.setdefaulttimeout(600)
sys.stdout.reconfigure(encoding="utf-8")
from google.oauth2.credentials import Credentials
from google.cloud import bigquery
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
# 日次OP別CCVR(1年OB+電話重複CV合算)は 1年OBシートと同一内容。生成/整形を共有(二重管理回避)。
from op_ccvr_to_sheets import build_ccvr_daily, ccvr_daily_fmt
TOKEN=r"C:\Users\syota\AppData\Roaming\gcloud\application_default_credentials.json"
SCOPES=["https://www.googleapis.com/auth/cloud-platform","https://www.googleapis.com/auth/drive"]
creds=Credentials.from_authorized_user_file(TOKEN,SCOPES)
bq=bigquery.Client(project="trustline-project",credentials=creds,location="asia-northeast1")
sheets=build("sheets","v4",credentials=creds); drive=build("drive","v3",credentials=creds)
BASE="`trustline-project.omni_call_log.base_denwacv`"
SS_NAME="電話重複CV_OP別CCVR"
BLOCK=["コール者","CT数","CV数","CVR"]; BW=len(BLOCK); GAP=1
PROD_ORDER=["キラⅡ","キラDROP","ペルル美容液","キラ","ミカ","テナル","メンディー","ペルル"]
VARIANTS=[("チャレ","チャレ"),("集中","集中"),("合算",None)]
COLOR={"red":0.75,"green":0.7,"blue":0.95}
def cvr(cv,ct): return round(cv/ct,4) if ct else 0
def fetch(prod, course):
    conds=["`コール者` IS NOT NULL","`コール者`!=''"]; params=[]
    if prod: conds.append("`商品`=@prod"); params.append(bigquery.ScalarQueryParameter("prod","STRING",prod))
    else: conds.append(f"`商品` IN {tuple(PROD_ORDER)}")
    if course: conds.append("`コース`=@cs"); params.append(bigquery.ScalarQueryParameter("cs","STRING",course))
    sql=f"""WITH x AS (SELECT FORMAT_DATE('%Y-%m',DATE(`コール日時`)) ym,`コール者` op,`コンタクト` ct,`成約` cv
      FROM {BASE} WHERE {' AND '.join(conds)})
      SELECT ym,op,COUNTIF(ct) ct,COUNTIF(cv) cv FROM x GROUP BY ym,op"""
    data={}
    for r in bq.query(sql,job_config=bigquery.QueryJobConfig(query_parameters=params)).result():
        data.setdefault(r.ym,[]).append((r.op,r.ct,r.cv))
    return data
def build_grid(data,flabel):
    months=sorted(data.keys(),reverse=True)
    for ym in months: data[ym].sort(key=lambda t:(cvr(t[2],t[1]),t[1]),reverse=True)
    maxops=max((len(v) for v in data.values()),default=0)
    grid=[["" for _ in range(len(months)*(BW+GAP))] for _ in range(3+maxops)]
    for mi,ym in enumerate(months):
        c0=mi*(BW+GAP); grid[0][c0]=f"{int(ym[5:7])}月{flabel}"
        for j,h in enumerate(BLOCK): grid[1][c0+j]=h
        tct=sum(t[1] for t in data[ym]); tcv=sum(t[2] for t in data[ym])
        grid[2][c0:c0+BW]=["全体",tct,tcv,cvr(tcv,tct)]
        for k,(op,ct,cv) in enumerate(data[ym]): grid[3+k][c0:c0+BW]=[op,ct,cv,cvr(cv,ct)]
    return grid,len(months)*(BW+GAP),len(months)
def main():
    tabs=[]   # (title, grid, ncol, nm, kind)  kind: "block"=月ブロック / "daily"=日次OP転置
    # 先頭: OP別CCVR_日次(1年OB+電話重複CV合算・日別転置)。1年OBシートと同一内容。
    cres=build_ccvr_daily()
    if cres:
        cgrid,cncol,cnblk=cres
        tabs.append(("OP別CCVR_日次",cgrid,cncol,cnblk,"daily"))
    for suf,cs in VARIANTS:
        g,ncol,nm=build_grid(fetch(None,cs),suf)
        if nm: tabs.append((f"全商材_{suf}",g,ncol,nm,"block"))
    for prod in PROD_ORDER:
        for suf,cs in VARIANTS:
            g,ncol,nm=build_grid(fetch(prod,cs),suf)
            if nm: tabs.append((f"{prod}_{suf}",g,ncol,nm,"block"))
    print(f"対象タブ: {len(tabs)}")
    r=drive.files().list(q=f"name='{SS_NAME}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",fields="files(id)").execute().get("files",[])
    ss_id=r[0]["id"] if r else sheets.spreadsheets().create(body={"properties":{"title":SS_NAME}}).execute()["spreadsheetId"]
    _meta=sheets.spreadsheets().get(spreadsheetId=ss_id).execute()["sheets"]
    old=[s["properties"]["sheetId"] for s in _meta]
    _titles={s["properties"]["title"] for s in _meta}  # 中断で残った_tmpと衝突しない空き名を選ぶ(残骸はold削除で掃除)
    _tmpname="_tmp"; _i=0
    while _tmpname in _titles: _i+=1; _tmpname=f"_tmp{_i}"
    tmp=sheets.spreadsheets().batchUpdate(spreadsheetId=ss_id,body={"requests":[{"addSheet":{"properties":{"title":_tmpname}}}]}).execute()["replies"][0]["addSheet"]["properties"]["sheetId"]
    sheets.spreadsheets().batchUpdate(spreadsheetId=ss_id,body={"requests":[{"deleteSheet":{"sheetId":s}} for s in old]}).execute()
    add=[{"addSheet":{"properties":{"title":t[0],"gridProperties":{"rowCount":len(t[1])+5,"columnCount":max(t[2],1),"frozenRowCount":3}}}} for t in tabs]
    res=sheets.spreadsheets().batchUpdate(spreadsheetId=ss_id,body={"requests":add}).execute()
    tid={rp["addSheet"]["properties"]["title"]:rp["addSheet"]["properties"]["sheetId"] for rp in res["replies"]}
    sheets.spreadsheets().batchUpdate(spreadsheetId=ss_id,body={"requests":[{"deleteSheet":{"sheetId":tmp}}]}).execute()
    fmt=[]
    for title,grid,ncol,nm,kind in tabs:
        sheets.spreadsheets().values().update(spreadsheetId=ss_id,range=f"'{title}'!A1",valueInputOption="USER_ENTERED",body={"values":grid}).execute()
        sid=tid[title]
        if kind=="daily":   # 日次OP別CCVR(転置)。整形は共有関数(_CCVR_META は直前のbuild_ccvr_dailyが設定済)
            fmt+=ccvr_daily_fmt(sid,grid,ncol,nm)
            print(f"  書込: {title} ({len(grid)}行 / 合計+OP{nm-1}×3列)")
            continue
        for mi in range(nm):
            c0=mi*(BW+GAP)
            fmt.append({"mergeCells":{"mergeType":"MERGE_ALL","range":{"sheetId":sid,"startRowIndex":0,"endRowIndex":1,"startColumnIndex":c0,"endColumnIndex":c0+BW}}})
            cc=c0+3
            fmt.append({"repeatCell":{"range":{"sheetId":sid,"startRowIndex":2,"startColumnIndex":cc,"endColumnIndex":cc+1},"cell":{"userEnteredFormat":{"numberFormat":{"type":"PERCENT","pattern":"0.00%"}}},"fields":"userEnteredFormat.numberFormat"}})
        fmt.append({"repeatCell":{"range":{"sheetId":sid,"startRowIndex":0,"endRowIndex":3},"cell":{"userEnteredFormat":{"horizontalAlignment":"CENTER","textFormat":{"bold":True}}},"fields":"userEnteredFormat(horizontalAlignment,textFormat)"}})
        fmt.append({"updateSheetProperties":{"properties":{"sheetId":sid,"tabColor":COLOR},"fields":"tabColor"}})
        print(f"  書込: {title} ({len(grid)}行 / {nm}月)")
    for i in range(0,len(fmt),100):
        for attempt in range(5):
            try: sheets.spreadsheets().batchUpdate(spreadsheetId=ss_id,body={"requests":fmt[i:i+100]}).execute(); break
            except (TimeoutError,OSError,HttpError):
                if attempt==4: raise
                time.sleep(5*(attempt+1))
    print("完了:", f"https://docs.google.com/spreadsheets/d/{ss_id}/edit")
if __name__=="__main__": main()
