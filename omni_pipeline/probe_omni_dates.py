# -*- coding: utf-8 -*-
"""電話重複CV集計テンプレのダウンロード画面で、日付条件の構成を調査する。
   cbDateType のオプション、日付系input(id/name/value)、コール日/最終コール系selectを出力。
   使い方: OMNI_HOST=wellmedia python probe_omni_dates.py
"""
import os, sys, json
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("OMNI_HEADLESS", "1")
from playwright.sync_api import sync_playwright
import extract_omni as E

TMPL = os.environ.get("OMNI_TEMPLATE", "電話重複CV集計")

with sync_playwright() as p:
    ctx, page = E._new_context(p)
    try:
        frame = E._get_main_frame(page)
        frame.goto(E.DOWNLOAD_URL)
        frame.wait_for_selector("#cbTempList", timeout=30000)
        # テンプレ選択
        res = frame.evaluate("""(name)=>{const s=document.getElementById('cbTempList');let v=null;
          for(const o of s.options){if(o.text.trim()===name){v=o.value;break;}}
          if(v===null)for(const o of s.options){if(o.text.includes(name)){v=o.value;break;}}
          if(v!==null){s.value=v;s.dispatchEvent(new Event('change',{bubbles:true}));}return v;}""", TMPL)
        print("template value:", res)
        frame.wait_for_timeout(1500)
        try:
            frame.locator("#btnTempSubmit").click(); frame.wait_for_timeout(2500)
        except Exception as ex:
            print("btnTempSubmit click skip:", ex)
        info = frame.evaluate("""()=>{
          const out={selects:[],dateInputs:[]};
          for(const s of document.querySelectorAll('select')){
            const opts=[...s.options].map(o=>({t:o.text.trim(),v:o.value,sel:o.selected}));
            if(opts.length>25) continue;  // 巨大な項目リストselectは除外
            const joined=opts.map(o=>o.t).join('|');
            if(/日|コール|期間|注文|種別|条件|date|Date|Type/.test((s.id||'')+(s.name||'')+joined)){
              out.selects.push({id:s.id,name:s.name,value:s.value,options:opts});
            }
          }
          for(const i of document.querySelectorAll('input')){
            const key=(i.id||'')+(i.name||'')+(i.placeholder||'');
            if(/Time|Date|date|day|Day|期間|日|コール|注文|From|To/.test(key)){
              const st=i.currentStyle||window.getComputedStyle(i);
              out.dateInputs.push({id:i.id,name:i.name,type:i.type,value:i.value,ph:i.placeholder,vis:st.display!=='none'&&st.visibility!=='hidden'});
            }
          }
          return out;}""")
        print("\n=== 日付系 SELECT ===")
        for s in info["selects"]:
            print(f"  id={s['id']!r} name={s['name']!r} value={s['value']!r}")
            for o in s["options"]:
                mark="  <== selected" if o["sel"] else ""
                print(f"      [{o['v']}] {o['t']!r}{mark}")
        print("\n=== 日付系 INPUT ===")
        for i in info["dateInputs"]:
            print(f"  id={i['id']!r} name={i['name']!r} type={i['type']} vis={i['vis']} value={i['value']!r} ph={i['ph']!r}")
    finally:
        ctx.close()
