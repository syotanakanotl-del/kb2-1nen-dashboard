# -*- coding: utf-8 -*-
"""オムニコンタクト管理画面から前日分のコール履歴CSVをダウンロードする。

永続プロファイル方式:
  - 初回だけ手動ログイン（cookie等を .pwprofile に保存）。以降は自動で再利用。

モード:
  python extract_omni.py setcreds 認証情報(ID/パスワード)をWindows資格情報マネージャーに保存。
  python extract_omni.py login    初回セットアップ。ブラウザを開いて手動ログイン。
                                   ログインできたらこのターミナルで Enter を押す。
  python extract_omni.py          日次実行。前日分CSVを OUT_DIR にDLしてパスを表示。
  python extract_omni.py 20260620 任意日付（YYYYMMDD）を指定してDL。

セッション切れ時は、保存済み認証情報で自動再ログインする（setcreds 済みが前提）。
"""
import sys, os, datetime, getpass
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
import keyring

# ---- 設定 -------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "data")               # DLしたCSVの保存先

# オムニのテナント(サブドメイン)。既定=wellmedia(従来)。
# プレプラ等の別アカウントは OMNI_HOST=trustingline のように切替。
OMNI_HOST = os.environ.get("OMNI_HOST", "wellmedia")
_ORIGIN = f"https://{OMNI_HOST}.omni-contact.net/"
LOGIN_URL = _ORIGIN + "login/index"
BASE_URL = _ORIGIN                                  # ログイン後に開く起点
DOWNLOAD_URL = _ORIGIN + "Download/index/"

# ログインセッション(Cookie等)保存先。テナント毎に分離。
# 既定wellmediaは従来の `.pwprofile` を維持(後方互換)、別テナントは `.pwprofile_<host>`。
USER_DATA_DIR = os.path.join(
    HERE, ".pwprofile" if OMNI_HOST == "wellmedia" else f".pwprofile_{OMNI_HOST}")

# ダウンロード画面のテンプレート名（cbTempList のオプションをこの名前で選択）
# 環境変数 OMNI_TEMPLATE で上書き可（既定=1年OB。単品OB等の別テンプレ取得に使う）
TEMPLATE_NAME = os.environ.get("OMNI_TEMPLATE", "1年OB集計全商品")
# 出力CSVのファイル名プレフィックス（環境変数 OMNI_OUT_PREFIX で上書き、既定=omni）
OUT_PREFIX = os.environ.get("OMNI_OUT_PREFIX", "omni")
# 期間をテンプレの相対日ではなく明示的に「前日」へ上書きするか
OVERRIDE_DATE = True
# 日付条件(cbConditionType)をenvで固定。テンプレの保存状態に依存させない防御。
#   'Wt02CallHistory.created'=コール日 / 'Wt01HearingTbl.latest_call_time'=最終コール日時。
#   未指定(既定)ならテンプレの保存値のまま。電話重複CVは「コール日」を強制する。
CONDITION_TYPE = os.environ.get("OMNI_CONDITION_TYPE")

# 環境変数 OMNI_HEADLESS=1 で画面なし実行（既定は画面ありで安定）
HEADLESS = os.environ.get("OMNI_HEADLESS", "0") == "1"

# 認証情報の保存先（Windows資格情報マネージャー）。テナント毎に分離。
# 既定wellmediaは従来の `omni-contact` を維持(後方互換)、別テナントは `omni-contact-<host>`。
KEYRING_SERVICE = "omni-contact" if OMNI_HOST == "wellmedia" else f"omni-contact-{OMNI_HOST}"
KEYRING_USER_KEY = "_user_code"   # ユーザーIDを保存するキー
# ----------------------------------------------------------------------


def do_setcreds():
    """ユーザーID/パスワードをWindows資格情報マネージャーに保存。"""
    user = input("オムニコンタクトのユーザーID: ").strip()
    pw = getpass.getpass("パスワード（入力は表示されません）: ")
    pw2 = getpass.getpass("確認のためもう一度パスワード: ")
    if pw != pw2:
        sys.exit("パスワードが一致しません。もう一度 setcreds を実行してください。")
    if not pw:
        sys.exit("パスワードが空です。")
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER_KEY, user)
    keyring.set_password(KEYRING_SERVICE, user, pw)
    print(f"保存しました（service={KEYRING_SERVICE}, user={user}, パスワード{len(pw)}文字）。")
    print("→ 文字数が想定と違う場合は、貼り付けミス等の可能性。再実行してください。")


def _get_creds():
    user = keyring.get_password(KEYRING_SERVICE, KEYRING_USER_KEY)
    pw = keyring.get_password(KEYRING_SERVICE, user) if user else None
    return user, pw


def _auto_login(page):
    """保存済み認証情報でログインフォームを送信する。"""
    user, pw = _get_creds()
    if not user or not pw:
        raise RuntimeError(
            "認証情報が未保存です。`python extract_omni.py setcreds` で保存してください。"
        )
    page.goto(LOGIN_URL, wait_until="networkidle")
    page.fill("#UserU_code", user)
    page.fill("#UserU_password", pw)
    # 多重ログイン制御: 既存セッションがあっても強制ログイン
    page.evaluate(
        """() => { const f = document.getElementById('force_login_flag'); if (f) f.value = '1'; }"""
    )
    page.click("#lnkSubmit")
    # 遷移完了を待つ（networkidleだけだとクリック直後に早期return することがある）
    try:
        page.wait_for_url(lambda u: "login" not in u.lower(), timeout=20000)
    except Exception:
        pass
    page.wait_for_load_state("networkidle")
    if "login" in page.url.lower():
        raise RuntimeError(f"自動ログイン失敗（ID/パスワード誤り等）: {page.url}")
    print("  自動再ログイン成功")


def target_date(argv):
    """引数があれば YYYYMMDD をその日付に、無ければ前日(JST)。"""
    if len(argv) > 1 and argv[1].isdigit():
        return datetime.datetime.strptime(argv[1], "%Y%m%d").date()
    jst = datetime.timezone(datetime.timedelta(hours=9))
    return (datetime.datetime.now(jst) - datetime.timedelta(days=1)).date()


def do_login():
    """手動ログイン用にブラウザを開き、Enterまで待つ。"""
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(USER_DATA_DIR, headless=False, accept_downloads=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LOGIN_URL)
        print("ブラウザでログインしてください。完了したらこのウィンドウで Enter を押す...")
        input()
        ctx.close()
        print("ログインセッションを保存しました:", USER_DATA_DIR)


def do_record():
    """保存済みログインのまま操作を録画する。
    Inspectorが開くので「Record」を押し、CSVダウンロードまでの操作を実行。
    生成されたPythonコードをコピーして _download_flow に貼り付ける。
    """
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(USER_DATA_DIR, headless=False, accept_downloads=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LOGIN_URL)
        print("Inspectorの『Record』を押して、CSVダウンロードまで操作してください。")
        print("生成コードをコピーしたらブラウザを閉じてください。")
        page.pause()
        ctx.close()


def do_diag():
    """診断: 手動でレポート画面まで進めてもらい、iframeのURLと要素を出力する。
    これで安定したURL直行＋セレクタを作る。
    """
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(USER_DATA_DIR, headless=False, accept_downloads=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(BASE_URL)
        print("=" * 60)
        print("ブラウザで『年OBキラⅡ集計』を選んで【ダウンロードできる状態】まで")
        print("手動で進めてください。そこまで来たら Inspector の Resume を押す。")
        print("=" * 60)
        page.pause()

        print("\n--- 全フレームのURL ---")
        for fr in page.frames:
            print(f"  name={fr.name!r}  url={fr.url}")

        # 'main'フレーム(=Download画面)から、キーワードに一致する要素を id/href 付きで精密に拾う
        terms = ["集計", "反映", "ダウンロード", "My設定", "1年OB", "キラ", "検索", "保存"]
        for fr in page.frames:
            if "Download/index" not in fr.url:
                continue
            try:
                info = fr.evaluate(
                    """(terms) => {
                        const hit = (t) => terms.some(k => t && t.includes(k));
                        const desc = (e) => ({
                          tag: e.tagName.toLowerCase(),
                          id: e.id || null,
                          cls: e.className || null,
                          href: e.getAttribute && e.getAttribute('href'),
                          onclick: e.getAttribute && e.getAttribute('onclick'),
                          text: (e.innerText||e.value||'').trim().slice(0,40),
                        });
                        const els = [...document.querySelectorAll('a,button,li,div,span,input')];
                        const matched = els.filter(e => {
                          const t = (e.innerText||e.value||'').trim();
                          return t && hit(t) && t.length < 30;
                        }).map(desc);
                        // 日付入力欄の候補
                        const dateInputs = [...document.querySelectorAll('input')]
                          .filter(i => /date|day|期間|日/.test((i.id||'')+(i.name||'')+(i.placeholder||'')))
                          .map(i => ({id:i.id, name:i.name, type:i.type, value:i.value, ph:i.placeholder}));
                        const cur = (id) => { const s=document.getElementById(id); return s? s.value : null; };
                        return {
                          matched,
                          dateInputs,
                          current: {
                            downloadType: cur('cbDownloadType'),
                            conditionType: cur('cbConditionType'),
                            dateType: cur('cbDateType'),
                            tempList: cur('cbTempList'),
                          }
                        };
                    }""",
                    terms,
                )
                print(f"\n--- Download画面 一致要素 (id/href付き) ---")
                for m in info["matched"]:
                    print(f"  [{m['tag']}] id={m['id']} href={m['href']} onclick={m['onclick']} text={m['text']!r}")
                print("\n--- 日付入力候補 ---")
                for di in info["dateInputs"]:
                    print(f"  {di}")
                print("\n--- 現在の選択値 ---", info["current"])
            except Exception as e:
                print(f"  （読めず: {e}）")
        ctx.close()


def _get_main_frame(page):
    """ログイン後ページから 'main' フレーム(=Download画面コンテナ)を取得。
    セッション切れ時は保存済み認証情報で自動再ログインして1回だけリトライ。
    """
    for attempt in range(2):
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")
        # ログイン画面に飛ばされたら自動ログイン
        if "login" in page.url.lower():
            if attempt == 0:
                print("  セッション切れ → 自動再ログインを試行")
                _auto_login(page)
                continue
            raise RuntimeError(f"自動再ログイン後もログイン画面: {page.url}")
        for _ in range(40):
            fr = page.frame(name="main")
            if fr:
                return fr
            page.wait_for_timeout(500)
        # mainが出ない（ログイン画面ではない）→ 診断して終了
        raise RuntimeError(
            f"'main' フレームが見つかりません。現在URL={page.url} / "
            f"frames={[f.name for f in page.frames]}"
        )
    raise RuntimeError("ログイン状態を確立できませんでした")


def _download_flow(page, date_from, date_to):
    """Download画面を安定IDで操作してCSVをDLする。
    テンプレ適用 → 期間を [date_from, date_to] に上書き → ダウンロード。
    date_from/date_to: date。単日なら同じ値を渡す。
    ※ダイアログ自動OKは呼び出し側で page.on('dialog', ...) を1回だけ登録すること。
    """
    frame = _get_main_frame(page)
    frame.goto(DOWNLOAD_URL)
    frame.wait_for_selector("#cbTempList", timeout=30000)

    # テンプレートを名前で選択して change を発火 → 反映
    res = frame.evaluate(
        """(name) => {
            const s = document.getElementById('cbTempList');
            let val = null;
            for (const o of s.options) { if (o.text.trim() === name) { val = o.value; break; } }
            if (val === null) { for (const o of s.options) { if (o.text.includes(name)) { val = o.value; break; } } }
            if (val !== null) {
                s.value = val;
                s.dispatchEvent(new Event('change', {bubbles:true}));
            }
            const sample = [...s.options].map(o => o.text.trim())
                .filter(t => t.includes('全商品') || t.includes('1年OB集計')).slice(0, 30);
            return { val, sample };
        }""",
        TEMPLATE_NAME,
    )
    if res["val"] is None:
        raise RuntimeError(
            f"テンプレ '{TEMPLATE_NAME}' が cbTempList に見つかりません。"
            f"近い候補: {res['sample']}"
        )
    print(f"  テンプレ選択: {TEMPLATE_NAME} (value={res['val']})")
    frame.wait_for_timeout(1000)
    frame.locator("#btnTempSubmit").click()      # 反映
    frame.wait_for_timeout(2000)

    if CONDITION_TYPE:
        # 日付条件(コール日/最終コール日時)をテンプレ状態に依存せず明示指定(value優先・text後方一致)
        r = frame.evaluate(
            """(want) => {
                const s = document.getElementById('cbConditionType');
                if (!s) return 'no-select';
                let hit = null;
                for (const o of s.options) { if (o.value === want) { hit = o.value; break; } }
                if (hit === null) for (const o of s.options) { if (o.text.trim() === want) { hit = o.value; break; } }
                if (hit !== null) { s.value = hit; s.dispatchEvent(new Event('change', {bubbles:true})); return 'set:' + hit; }
                return 'notfound:' + [...s.options].map(o => o.value + '=' + o.text.trim()).join(',');
            }""",
            CONDITION_TYPE,
        )
        print(f"  日付条件(cbConditionType)={CONDITION_TYPE} -> {r}")
        frame.wait_for_timeout(500)

    if OVERRIDE_DATE:
        # 期間タイプを「期間設定」にして from/to を指定範囲に上書き
        frame.evaluate(
            """([f, t]) => {
                const dt = document.getElementById('cbDateType');
                if (dt) {
                    for (const o of dt.options) {
                        if (o.text.includes('期間設定')) { dt.value = o.value; break; }
                    }
                    dt.dispatchEvent(new Event('change', {bubbles:true}));
                }
                const set = (id, v) => {
                    const e = document.getElementById(id);
                    if (e) {
                        e.value = v;
                        e.dispatchEvent(new Event('change', {bubbles:true}));
                        e.dispatchEvent(new Event('input', {bubbles:true}));
                    }
                };
                set('txLatestCallTimeFrom', f);
                set('txLatestCallTimeTo', t);
            }""",
            [date_from.strftime("%Y/%m/%d"), date_to.strftime("%Y/%m/%d")],
        )
        frame.wait_for_timeout(1000)

    # DL待ち上限。画面ロック中などで応答しないとき10分ハングを避けるため3分に短縮
    # (通常のCSV生成は1分前後。ロック中はラッパー側でSTEP Bを事前スキップする)
    dl_timeout = int(os.environ.get("OMNI_DL_TIMEOUT_MS", "180000"))
    with page.expect_download(timeout=dl_timeout) as dl:
        frame.locator("#btnDownLoad").click()    # ダウンロード
    return dl.value


def _new_context(p):
    ctx = p.chromium.launch_persistent_context(
        USER_DATA_DIR, headless=HEADLESS, accept_downloads=True
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("dialog", lambda dialog: dialog.accept())  # 確認/アラートは自動OK(1回だけ登録)
    return ctx, page


def do_download(d):
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{OUT_PREFIX}_{d:%Y%m%d}.csv")
    with sync_playwright() as p:
        ctx, page = _new_context(p)
        try:
            download = _download_flow(page, d, d)
            download.save_as(out_path)
            print("ダウンロード完了:", out_path)
        finally:
            ctx.close()
    return out_path


def do_download_range(d_from, d_to):
    """[d_from, d_to] の期間をまとめて1CSVでDL(バックフィルの月チャンク用)。
    ファイル名 = <prefix>_<from>_<to>.csv。取込側は DATE(コール日時) 単位で冪等。"""
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{OUT_PREFIX}_{d_from:%Y%m%d}_{d_to:%Y%m%d}.csv")
    with sync_playwright() as p:
        ctx, page = _new_context(p)
        try:
            download = _download_flow(page, d_from, d_to)
            download.save_as(out_path)
            print("ダウンロード完了:", out_path)
        finally:
            ctx.close()
    return out_path


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "setcreds":
        do_setcreds()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "login":
        do_login()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "record":
        do_record()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "diag":
        do_diag()
        return
    # 2つの YYYYMMDD → 期間まとめてDL(バックフィル用)
    if (len(sys.argv) > 2 and sys.argv[1].isdigit() and sys.argv[2].isdigit()):
        d1 = datetime.datetime.strptime(sys.argv[1], "%Y%m%d").date()
        d2 = datetime.datetime.strptime(sys.argv[2], "%Y%m%d").date()
        print(f"=== 期間: {d1:%Y-%m-%d} 〜 {d2:%Y-%m-%d} ===")
        do_download_range(d1, d2)
        return
    d = target_date(sys.argv)
    print(f"=== 対象日付: {d:%Y-%m-%d} ===")
    do_download(d)


if __name__ == "__main__":
    main()
