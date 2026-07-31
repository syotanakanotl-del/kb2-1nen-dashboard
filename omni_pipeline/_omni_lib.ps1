# オムニ取込 共有ライブラリ（dot-source専用。トップレベル実行コード無し）。
#   $OmniTableRegistry : 取込対象6テーブルの定義(1年OB/単品/プレプラ/休眠/かご落ち/電話重複CV)。
#   Invoke-OmniDayData : 指定1日分のテーブルを extract+load(データのみ)。-Tables で対象を絞れる。
#                        戻り値=@{key=$true/$false} 各テーブルの取込成否(per-table marker用)。
#   Invoke-OmniSheets  : 全スプレッドシート更新を1回実行(マートはビューなので最新データを反映)。
# 日次ラッパー run_omni_daily.ps1 とバックフィル backfill_omni_days.ps1 の両方から呼ぶ。
# load_*_to_bq.py は「同日をDELETE→INSERT」で冪等なので、同じ日を何度流しても重複しない。

# 取込テーブル定義(処理順)。host='' はwellmedia(既定)、tmpl='' は1年OB既定テンプレ。
# table='' は既定 call_history、prefix は data\<prefix>_<ymd>.csv とextractの出力名。
$OmniTableRegistry = @(
    @{ key = "ichinen";  host = "";             tmpl = "";                                  prefix = "omni";       table = "";                    load = "load_omni_to_bq.py" },
    @{ key = "tanpin";   host = "";             tmpl = "単品OB集計全商品";                  prefix = "omni_tanpin"; table = "call_history_tanpin"; load = "load_omni_to_bq.py" },
    @{ key = "prepla";   host = "trustingline"; tmpl = "架電検証全商材プレプラ【BQ取り込み用】"; prefix = "prepla";  table = ""; load = "load_prepla_to_bq.py" },
    @{ key = "dormant";  host = "trustingline"; tmpl = "架電検証全商材休眠";                 prefix = "dormant";    table = ""; load = "load_dormant_to_bq.py" },
    @{ key = "kagoochi"; host = "trustingline"; tmpl = "かご落ちOB全商材";                   prefix = "kagoochi";   table = ""; load = "load_kagoochi_to_bq.py" },
    # 電話重複CVは日付条件を「コール日」に固定(cond)。テンプレが最終コール日時に戻っても影響を受けない防御。
    @{ key = "denwacv";  host = "trustingline"; tmpl = "電話重複CV集計";                     prefix = "denwacv";    table = ""; load = "load_denwacv_to_bq.py"; cond = "Wt02CallHistory.created" },
    # 電話重複CVはwellmediaテナントにも同名テンプレがある。両テナントを同一テーブルへ集約(テナント列で分離)。
    @{ key = "denwacv_wm"; host = "wellmedia"; tmpl = "電話重複CV集計";                        prefix = "denwacvwm";  table = ""; load = "load_denwacv_to_bq.py"; cond = "Wt02CallHistory.created" }
)
$OmniTableKeys = $OmniTableRegistry | ForEach-Object { $_.key }

function Write-OmniLog {
    param([string]$LogFile, [string]$Msg)
    "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $Msg" | Out-File -FilePath $LogFile -Encoding utf8 -Append
}

function Invoke-OmniDayData {
    # 指定日(YYYYMMDD)の各テーブルを extract+load。-Tables で対象keyを絞る(既定=全6)。
    # 戻り値=@{key=$bool}(処理したテーブルの成否)。失敗は警告のみでジョブは止めない。
    param(
        [Parameter(Mandatory)][string]$Ymd,
        [Parameter(Mandatory)][string]$Py,
        [Parameter(Mandatory)][string]$Pipe,
        [Parameter(Mandatory)][string]$LogFile,
        [string[]]$Tables = $OmniTableKeys
    )
    $results = @{}
    foreach ($t in $OmniTableRegistry) {
        if ($Tables -notcontains $t.key) { continue }
        Write-OmniLog $LogFile "--- [$Ymd] extract+load ($($t.key)) ---"
        # extract用env(テーブル毎に完全設定→finallyで必ず戻す。順序非依存)
        if ($t.host) { $env:OMNI_HOST = $t.host } else { Remove-Item Env:OMNI_HOST -ErrorAction SilentlyContinue }
        if ($t.tmpl) { $env:OMNI_TEMPLATE = $t.tmpl } else { Remove-Item Env:OMNI_TEMPLATE -ErrorAction SilentlyContinue }
        if ($t.cond) { $env:OMNI_CONDITION_TYPE = $t.cond } else { Remove-Item Env:OMNI_CONDITION_TYPE -ErrorAction SilentlyContinue }
        $env:OMNI_OUT_PREFIX = $t.prefix
        $ok = $false
        try {
            $csv = Join-Path $Pipe "data\$($t.prefix)_$Ymd.csv"
            & $Py -u "$Pipe\extract_omni.py" $Ymd *>&1 | Out-File -FilePath $LogFile -Encoding utf8 -Append
            if ($LASTEXITCODE -ne 0) {
                Write-OmniLog $LogFile "!!! 警告: [$Ymd] $($t.key) extract 失敗 (exit=$LASTEXITCODE)"
            } elseif (-not (Test-Path $csv)) {
                Write-OmniLog $LogFile "!!! 警告: [$Ymd] $($t.key) CSV未生成"
            } else {
                if ($t.table) { $env:OMNI_TABLE = $t.table } else { Remove-Item Env:OMNI_TABLE -ErrorAction SilentlyContinue }
                & $Py -u "$Pipe\$($t.load)" $csv *>&1 | Out-File -FilePath $LogFile -Encoding utf8 -Append
                if ($LASTEXITCODE -eq 0) { $ok = $true } else { Write-OmniLog $LogFile "!!! 警告: [$Ymd] $($t.key) load 失敗 (exit=$LASTEXITCODE)" }
                Remove-Item Env:OMNI_TABLE -ErrorAction SilentlyContinue
                # trustingline系はCSVを掃除(容量節約。1年OB/単品は従来通り残す)
                if ($t.host) { Remove-Item $csv -ErrorAction SilentlyContinue }
            }
        }
        finally {
            Remove-Item Env:OMNI_HOST, Env:OMNI_TEMPLATE, Env:OMNI_OUT_PREFIX, Env:OMNI_CONDITION_TYPE -ErrorAction SilentlyContinue
        }
        $results[$t.key] = $ok
    }
    return $results
}

function Invoke-OmniSheets {
    # 全スプレッドシート更新を1回実行。マートはビューなので、取込済みの全日分が自動反映される。
    # 個々の失敗は警告のみ(取込は既に完了しているため)。
    param(
        [Parameter(Mandatory)][string]$Py,
        [Parameter(Mandatory)][string]$Pipe,
        [Parameter(Mandatory)][string]$LogFile
    )
    $steps = @(
        @{ msg = "不在数コホート";                  script = "cohort_to_sheets.py";           args = @() },
        @{ msg = "OP別CCVR";                        script = "op_ccvr_to_sheets.py";          args = @() },
        @{ msg = "新規vsOB";                        script = "new_vs_ob_to_sheets.py";        args = @() },
        @{ msg = "1年OB集計 対新規コホート";        script = "cohort_daystage_to_sheets.py";  args = @() },
        @{ msg = "1年OB 曜日別CT率CVR";             script = "dow_ccvr_1nen_to_sheets.py";     args = @() },
        @{ msg = "単品OB集計 対新規コホート";       script = "cohort_tanpin_to_sheets.py";    args = @() },
        @{ msg = "プレプラ first4マップ";           script = "build_prepla_first4.py";        args = @() },
        @{ msg = "プレプラCCVR";                    script = "op_ccvr_prepla_to_sheets.py";   args = @() },
        @{ msg = "プレプラ不在数別CT・CVR";         script = "cohort_prepla_to_sheets.py";    args = @() },
        @{ msg = "プレミアム 対4回受取コホート";    script = "ext_daystage_to_sheets.py";     args = @("prem") },
        @{ msg = "プラチナ 対4回受取コホート";      script = "ext_daystage_to_sheets.py";     args = @("plat") },
        @{ msg = "休眠不在数別CT・CVR";             script = "cohort_dormant_to_sheets.py";   args = @() },
        @{ msg = "休眠 対解約コホート";             script = "ext_daystage_to_sheets.py";     args = @("dormant") },
        @{ msg = "休眠OP別CCVR";                    script = "op_ccvr_dormant_to_sheets.py";  args = @() },
        @{ msg = "かご落ちOP別CCVR";                script = "op_ccvr_kagoochi_to_sheets.py"; args = @() },
        @{ msg = "かご落ち不在数別CT・CVR";         script = "cohort_kagoochi_to_sheets.py";  args = @() },
        @{ msg = "かご落ち 対離脱数コホート";       script = "ext_daystage_to_sheets.py";     args = @("kagoochi") },
        @{ msg = "電話重複CV OP別CCVR";             script = "op_ccvr_denwacv_to_sheets.py";  args = @() },
        @{ msg = "電話重複CV 不在数集計";           script = "cohort_denwacv_to_sheets.py";   args = @() },
        @{ msg = "電話重複CV 対初回注文コホート";   script = "ext_daystage_to_sheets.py";     args = @("denwacv") },
        @{ msg = "全OB合算 OP別通話コンタクト";     script = "op_talk_allob_to_sheets.py";    args = @() }
    )
    foreach ($s in $steps) {
        Write-OmniLog $LogFile "--- sheets ($($s.msg)) ---"
        & $Py -u "$Pipe\$($s.script)" @($s.args) *>&1 | Out-File -FilePath $LogFile -Encoding utf8 -Append
        if ($LASTEXITCODE -ne 0) { Write-OmniLog $LogFile "!!! 警告: $($s.msg)シート更新失敗 (exit=$LASTEXITCODE)" }
    }
    # コンタクト分析 キラⅡ限定版(env DOW_PROD)。dow_ccvr_1nen_to_sheets.py を商品指定で再実行し別スプシ出力
    Write-OmniLog $LogFile "--- sheets (コンタクト分析_キラⅡ) ---"
    $env:DOW_PROD = "キラⅡ"
    & $Py -u "$Pipe\dow_ccvr_1nen_to_sheets.py" *>&1 | Out-File -FilePath $LogFile -Encoding utf8 -Append
    if ($LASTEXITCODE -ne 0) { Write-OmniLog $LogFile "!!! 警告: コンタクト分析_キラⅡシート更新失敗 (exit=$LASTEXITCODE)" }
    Remove-Item Env:DOW_PROD -ErrorAction SilentlyContinue
}
