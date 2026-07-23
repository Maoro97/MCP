# -*- coding: utf-8 -*-
"""
webapp.py — ממשק וובי מקומי להכנת קבצי טעינה לפריוריטי

מעלים קובץ אקסל, בוחרים מסך יעד, ומקבלים טבלת טעינה אינטראקטיבית:
תאים שגויים נצבעים באדום, מתקנים במקום, מוחקים שורות, ומפיקים קובץ טעינה.
תומך גם בקבצים "קשים": שורת כותרת שאינה ראשונה, וקבצים גדולים (עשרות אלפי
שורות) — שבהם מוצגות לתיקון רק השורות השגויות, והתקינות נשמרות בשרת.

הפעלה:  python webapp.py   ואז בדפדפן:  http://127.0.0.1:5000
"""

import io
import os
import re
import time
import uuid

import pandas as pd
from flask import (
    Flask, request, jsonify, render_template_string, send_from_directory, abort,
)

import main as core

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 80 * 1024 * 1024  # מגבלת העלאה: 80MB

WEB_OUTPUT = os.path.join(core.OUTPUT_DIR, "web")
_RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")

# בקבצים עד גודל זה — כל השורות ניתנות לעריכה בטבלה.
# מעל זה — מוצגות רק השורות השגויות (התקינות נשמרות בשרת) כדי לא להעמיס על הדפדפן.
FULL_GRID_LIMIT = 1500
# תקרת שורות שגויות שנשלחות לדפדפן בבת אחת (השאר נכנסות ישירות ל-rejected).
DISPLAY_CAP = 8000

# מאגר ריצות בזיכרון (כלי מקומי, משתמש יחיד): run_id -> נתוני הריצה
RUNS = {}
_RUNS_MAX = 40


def _store_run(screen, valid_records, reserved, overflow):
    run_id = uuid.uuid4().hex
    RUNS[run_id] = {
        "screen": screen, "valid": valid_records, "reserved": reserved,
        "overflow": overflow, "created": time.time(),
    }
    if len(RUNS) > _RUNS_MAX:  # ניקוי ריצות ישנות
        for old in sorted(RUNS, key=lambda k: RUNS[k]["created"])[:len(RUNS) - _RUNS_MAX]:
            RUNS.pop(old, None)
    return run_id


# ---------------------------------------------------------------------------
# עוזרים
# ---------------------------------------------------------------------------
def _columns_meta(mapping):
    return [{
        "target": c["target"], "source": c.get("source"),
        "constant": c.get("source") is None, "type": c.get("type", "text"),
    } for c in mapping["columns"]]


def _first_reason(cells):
    return next((c["error"] for c in cells if c["error"]), "")


def _sample_warnings(mapping, valid_records, limit=40):
    w = core.check_encoding(valid_records, mapping["columns"],
                            mapping.get("encoding", "windows-1255"))
    return w[:limit], len(w)


def _rejected_df(mapping, items):
    """items: רשימת (excel_row, {target:value}, reason)."""
    targets = [c["target"] for c in mapping["columns"]]
    data = []
    for excel_row, values, reason in items:
        row = dict(values)
        row["שורה"] = excel_row
        row["סיבת פסילה"] = reason
        data.append(row)
    return pd.DataFrame(data, columns=targets + ["שורה", "סיבת פסילה"])


# ---------------------------------------------------------------------------
# עמוד ההעלאה
# ---------------------------------------------------------------------------
UPLOAD = """
<!doctype html><html lang="he" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>הכנת קובץ טעינה — Priority ERP</title>
<style>
 :root{--bg:#f4f6fb;--card:#fff;--line:#e3e8f0;--ink:#1e2a3a;--muted:#6b7a90;--blue:#2563eb;--green:#16a34a;--red:#dc2626}
 *{box-sizing:border-box}body{margin:0;font-family:"Segoe UI",Arial,sans-serif;background:var(--bg);color:var(--ink);line-height:1.6}
 .wrap{max-width:760px;margin:0 auto;padding:30px 18px 60px}h1{font-size:24px;margin:0 0 4px}
 header p{color:var(--muted);margin:0 0 22px}
 .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px;margin-bottom:18px}
 label{display:block;font-weight:600;margin:0 0 6px}
 select,input[type=text],input[type=number]{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:9px;font-size:15px;font-family:inherit;background:#fff}
 .row{display:flex;gap:16px;flex-wrap:wrap}.row>div{flex:1;min-width:200px;margin-bottom:16px}
 .drop{border:2px dashed #c3ccdb;border-radius:12px;padding:26px;text-align:center;cursor:pointer;background:#fafbfe;transition:.15s}
 .drop.over{border-color:var(--blue);background:#eef3ff}.drop b{color:var(--blue)}.drop small{display:block;color:var(--muted);margin-top:6px}
 .fname{margin-top:10px;font-weight:600;color:var(--green)}
 button{background:var(--blue);color:#fff;border:0;border-radius:10px;padding:12px 26px;font-size:16px;font-weight:600;cursor:pointer;margin-top:10px}
 button:hover{background:#1d4ed8}.muted{color:var(--muted);font-size:14px}
 .err{background:#fef2f2;border:1px solid #fecaca;color:#991b1b;border-radius:12px;padding:16px 18px;white-space:pre-wrap}
 code{background:#eef1f7;padding:2px 6px;border-radius:5px}a.back{color:var(--blue);text-decoration:none;font-weight:600}
</style></head><body><div class="wrap">
 <header><h1>הכנת קובץ טעינה ל-Priority ERP</h1>
 <p>העלה קובץ אקסל ובחר מסך יעד — תקבל טבלת טעינה לתיקון שגיאות לפני הפקת הקובץ.</p></header>
 {% if error %}
  <div class="card"><div class="err">❌ {{ error }}</div>
   <p style="margin-top:14px"><a class="back" href="/">→ חזרה</a></p></div>
 {% else %}
  <form class="card" method="post" action="/process" enctype="multipart/form-data">
   {% if not screens %}<div class="err">לא נמצאו קבצי מיפוי בתיקיית <code>mappings/</code>.</div>
   {% else %}
   <div class="row">
    <div><label for="screen">מסך יעד</label><select id="screen" name="screen">
     {% for s in screens %}<option value="{{ s }}">{{ s }}</option>{% endfor %}</select></div>
    <div><label for="sheet">שם הגיליון (רשות)</label>
     <input type="text" id="sheet" name="sheet" placeholder="ברירת מחדל: הראשון"></div>
    <div><label for="header_row">שורת כותרת (רשות)</label>
     <input type="number" id="header_row" name="header_row" min="1" placeholder="זיהוי אוטומטי"></div>
   </div>
   <label>קובץ האקסל</label>
   <div class="drop" id="drop"><b>גרור לכאן קובץ</b> או לחץ לבחירה<small>קבצי .xlsx בלבד</small>
    <input type="file" id="file" name="file" accept=".xlsx" hidden required>
    <div class="fname" id="fname"></div></div>
   <button type="submit">טען לטבלה</button>{% endif %}
  </form>
  <p class="muted">הכל רץ מקומית על המחשב שלך — הקובץ לא נשלח לשום שרת חיצוני.
   הכלי מזהה אוטומטית את שורת הכותרת גם כשהיא לא בשורה הראשונה.</p>
 {% endif %}
</div><script>
 const drop=document.getElementById('drop'),file=document.getElementById('file'),fname=document.getElementById('fname');
 if(drop){drop.addEventListener('click',()=>file.click());
  file.addEventListener('change',()=>{if(file.files[0])fname.textContent='📄 '+file.files[0].name;});
  ['dragover','dragenter'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add('over');}));
  ['dragleave','drop'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove('over');}));
  drop.addEventListener('drop',ev=>{file.files=ev.dataTransfer.files;if(file.files[0])fname.textContent='📄 '+file.files[0].name;});}
</script></body></html>
"""


# ---------------------------------------------------------------------------
# עמוד טבלת הטעינה
# ---------------------------------------------------------------------------
GRID = """
<!doctype html><html lang="he" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>טבלת טעינה — {{ screen }}</title>
<style>
 :root{--bg:#f4f6fb;--card:#fff;--line:#e3e8f0;--ink:#1e2a3a;--muted:#6b7a90;--blue:#2563eb;--green:#16a34a;--red:#dc2626;--amber:#d97706}
 *{box-sizing:border-box}body{margin:0;font-family:"Segoe UI",Arial,sans-serif;background:var(--bg);color:var(--ink)}
 .wrap{max-width:1400px;margin:0 auto;padding:18px 16px 80px}h1{font-size:21px;margin:0 0 2px}
 .sub{color:var(--muted);font-size:14px;margin:0 0 14px}
 .bar{display:flex;gap:9px;align-items:center;flex-wrap:wrap;padding:8px 0 12px;border-bottom:1px solid var(--line);margin-bottom:12px}
 .pill{border-radius:999px;padding:6px 13px;font-weight:700;font-size:14px}
 .pill.tot{background:#eef2f7;color:#334155}.pill.ok{background:#dcfce7;color:#166534}.pill.bad{background:#fee2e2;color:#991b1b}
 button{border:0;border-radius:9px;padding:9px 16px;font-size:14px;font-weight:600;cursor:pointer}
 .b-check{background:#475569;color:#fff}.b-gen{background:var(--green);color:#fff}.b-check:hover{background:#334155}.b-gen:hover{background:#15803d}
 .spacer{flex:1}a.back{color:var(--blue);text-decoration:none;font-weight:600;font-size:14px}
 .chk{display:flex;align-items:center;gap:6px;font-size:13px;color:#334155}.chk input{width:16px;height:16px}
 .banner{background:#eff6ff;border:1px solid #bfdbfe;color:#1e40af;border-radius:10px;padding:10px 14px;margin:8px 0;font-size:14px}
 .tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:12px;background:#fff}
 table{border-collapse:collapse;width:100%;font-size:14px}
 th,td{border-bottom:1px solid var(--line);border-left:1px solid var(--line);padding:0;text-align:right;white-space:nowrap}
 th{background:#f7f9fc;padding:8px 10px;position:sticky;top:0;z-index:2}
 th .tgt{font-weight:700}th .src{display:block;font-weight:400;color:var(--muted);font-size:12px}
 th.col{cursor:grab;user-select:none}th.col:active{cursor:grabbing}
 th.col .grip{color:#94a3b8;font-size:12px;margin-left:5px}
 th.col.dragover{background:#dbeafe;box-shadow:inset 0 0 0 2px var(--blue)}
 th.col.dragging{opacity:.45}
 th.rownum,td.rownum{background:#f1f5f9;color:#64748b;text-align:center;font-size:12px;min-width:42px;padding:6px}
 th.act,td.act{text-align:center;min-width:38px;padding:2px}
 td input{border:0;background:transparent;width:100%;min-width:105px;padding:8px 10px;font:inherit;color:inherit;outline:none}
 td.bad{background:#fef2f2;position:relative}td.bad input{color:#b91c1c;font-weight:600}
 td.bad::after{content:"!";position:absolute;top:2px;left:4px;color:#dc2626;font-weight:800;font-size:11px}
 td input:focus{background:#eef3ff;box-shadow:inset 0 0 0 2px var(--blue)}
 td.const input{background:#f8fafc;color:#64748b}
 tr.rowbad td.rownum{background:#fee2e2;color:#991b1b;font-weight:700}
 .del{background:#fee2e2;color:#b91c1c;border-radius:6px;padding:4px 8px;font-size:13px;cursor:pointer;font-weight:700}
 .del:hover{background:#fecaca}
 .legend{display:flex;gap:16px;color:var(--muted);font-size:13px;margin:10px 2px;flex-wrap:wrap}
 .legend i{display:inline-block;width:13px;height:13px;border-radius:3px;vertical-align:middle;margin-left:5px}
 .msg{border-radius:10px;padding:11px 15px;margin:10px 0;font-weight:600}
 .msg.ok{background:#dcfce7;color:#166534}.msg.err{background:#fef2f2;color:#991b1b}
 .msg.warnbox{background:#fffbeb;color:#92400e;border:1px solid #fde68a;font-weight:500}
 .pager{display:flex;gap:8px;align-items:center;justify-content:center;margin:12px 0;font-size:14px;color:#334155}
 .pager button{background:#e2e8f0;color:#334155;padding:6px 12px}.pager button:disabled{opacity:.4;cursor:default}
 .dl{display:inline-block;background:var(--green);color:#fff;text-decoration:none;border-radius:9px;padding:10px 18px;font-weight:600;margin:6px 8px 6px 0}
 .dl.rej{background:var(--red)}.dl.rep{background:#475569}.hint{color:var(--muted);font-size:13px}
</style></head><body><div class="wrap">
 <h1>טבלת טעינה — מסך {{ screen }}</h1>
 <p class="sub">תקן תאים אדומים (רחף לראות סיבה), מחק שורות מיותרות, לחץ <b>בדוק מחדש</b>, ואז <b>צור קובץ טעינה</b>.</p>
 <div class="bar">
  <span class="pill tot" id="p-tot">סה״כ 0</span>
  <span class="pill ok" id="p-ok">תקינות 0</span>
  <span class="pill bad" id="p-bad">שגויות 0</span>
  <button class="b-check" onclick="revalidate()">🔄 בדוק מחדש</button>
  <button class="b-gen" onclick="generate()">⬇ צור קובץ טעינה</button>
  <label class="chk" id="filterwrap"><input type="checkbox" id="onlyerr" onchange="render()"> הצג רק שגויות</label>
  <span class="spacer"></span><a class="back" href="/">→ קובץ חדש</a>
 </div>
 <div id="banner"></div><div id="messages"></div>
 <div class="legend">
  <span><i style="background:#fef2f2;border:1px solid #fecaca"></i>תא שגוי לתיקון</span>
  <span><i style="background:#f8fafc;border:1px solid #e3e8f0"></i>ערך קבוע (לא לעריכה)</span>
  <span class="hint">🗑 מוחק שורה · ⋮⋮ גרור כותרת עמודה כדי לשנות את סדר הייצוא · התאריך תמיד dd/mm/yy</span>
 </div>
 <div class="tablewrap"><table id="grid"></table></div>
 <div class="pager" id="pager"></div>
 <p class="hint" id="dlarea"></p>
<script>
const GRID = {{ grid|tojson }};
const PAGE_SIZE = 100;
let page = 0;
let colOrder = GRID.columns.map((_, i) => i);   // סדר תצוגה/ייצוא של העמודות
const $ = id => document.getElementById(id);
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

function overall(){
  let good=0,bad=0;
  for(const r of GRID.rows){ if(r.valid) good++; else bad++; }
  return {total:GRID.server_valid+GRID.rows.length+GRID.overflow,
          valid:GRID.server_valid+good, invalid:bad+GRID.overflow};
}
function displayed(){
  const onlyErr = $('onlyerr').checked;
  const out=[];
  GRID.rows.forEach((r,gi)=>{ if(!onlyErr || !r.valid) out.push([gi,r]); });
  return out;
}
function render(){
  const cols=GRID.columns, disp=displayed();
  const pages=Math.max(1,Math.ceil(disp.length/PAGE_SIZE));
  if(page>=pages) page=pages-1; if(page<0) page=0;
  const slice=disp.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE);
  let h='<thead><tr><th class="act"></th><th class="rownum">#</th>';
  for(const ci of colOrder){ const c=cols[ci];
    h+='<th class="col" draggable="true" data-ci="'+ci+'" ondragstart="dragStart(event,'+ci+
       ')" ondragover="dragOver(event)" ondragleave="dragLeave(event)" ondrop="dropCol(event,'+ci+
       ')" ondragend="dragEnd(event)"><span class="grip">⋮⋮</span><span class="tgt">'+esc(c.target)+
       '</span><span class="src">'+(c.constant?'ערך קבוע':esc(c.source||''))+'</span></th>';
  }
  h+='</tr></thead><tbody>';
  for(const [gi,r] of slice){
    h+='<tr class="'+(r.valid?'':'rowbad')+'">'+
       '<td class="act"><span class="del" title="מחק שורה" onclick="delRow('+gi+')">🗑</span></td>'+
       '<td class="rownum">'+r.excel_row+'</td>';
    for(const ci of colOrder){
      const cell=r.cells[ci], c=cols[ci];
      const cls=(cell.error?'bad ':'')+(c.constant?'const':'');
      const title=cell.error?' title="'+esc(cell.error)+'"':'';
      const ro=c.constant?' readonly':'';
      h+='<td class="'+cls+'"'+title+'><input value="'+esc(cell.value)+'"'+ro+
         ' oninput="upd('+gi+','+ci+',this.value)"></td>';
    }
    h+='</tr>';
  }
  if(!slice.length) h+='<tr><td class="act"></td><td class="rownum">–</td><td colspan="'+cols.length+
     '" style="padding:16px;color:#16a34a;font-weight:600">אין שורות להצגה 🎉</td></tr>';
  h+='</tbody>'; $('grid').innerHTML=h;
  renderPager(disp.length,pages);
  updateCounts();
}
function renderPager(n,pages){
  if(pages<=1){ $('pager').innerHTML=''; return; }
  $('pager').innerHTML='<button onclick="page--;render()" '+(page===0?'disabled':'')+'>הקודם</button>'+
    '<span>עמוד '+(page+1)+' מתוך '+pages+' ('+n+' שורות)</span>'+
    '<button onclick="page++;render()" '+(page>=pages-1?'disabled':'')+'>הבא</button>';
}
function updateCounts(){
  const o=overall();
  $('p-tot').textContent='סה״כ '+o.total; $('p-ok').textContent='תקינות '+o.valid; $('p-bad').textContent='שגויות '+o.invalid;
}
function upd(gi,ci,val){ GRID.rows[gi].cells[ci].value=val; }
function delRow(gi){ GRID.rows.splice(gi,1); render(); }

// --- גרירת עמודות לשינוי סדר הייצוא ---
let dragFromCi=null;
function dragStart(e,ci){ dragFromCi=ci; e.currentTarget.classList.add('dragging');
  e.dataTransfer.effectAllowed='move'; }
function dragOver(e){ e.preventDefault(); e.currentTarget.classList.add('dragover'); }
function dragLeave(e){ e.currentTarget.classList.remove('dragover'); }
function dragEnd(e){ document.querySelectorAll('th.col').forEach(t=>t.classList.remove('dragover','dragging')); }
function dropCol(e,toCi){ e.preventDefault();
  document.querySelectorAll('th.col').forEach(t=>t.classList.remove('dragover'));
  const from=colOrder.indexOf(dragFromCi), to=colOrder.indexOf(toCi);
  if(from<0||to<0||from===to) return;
  const [m]=colOrder.splice(from,1); colOrder.splice(to,0,m); render();
}

function renderBanner(){
  let b='';
  if(GRID.mode==='errors')
    b+='<div class="banner">📁 קובץ גדול: '+GRID.server_valid.toLocaleString()+
       ' שורות תקינות נשמרו בשרת ויכללו בקובץ הטעינה. כאן מוצגות רק '+GRID.rows.length+
       ' השורות שדורשות תיקון'+(GRID.overflow>0?(' (ועוד '+GRID.overflow+' שורות שגויות שלא נכנסות לתצוגה)'):'')+'.</div>';
  if(GRID.warn_count>0)
    b+='<div class="msg warnbox">⚠ אזהרות קידוד ('+GRID.warn_count+'): תווים שלא ניתנים ל-windows-1255 יוחלפו ב-?. '+
       esc((GRID.warnings||[]).slice(0,2).join(' | '))+(GRID.warn_count>2?' ...':'')+'</div>';
  $('banner').innerHTML=b;
}
function collect(){
  return {screen:GRID.screen, run_id:GRID.run_id,
    rows:GRID.rows.map(r=>{const o={};r.cells.forEach(c=>o[c.target]=c.value);return o;}),
    excel_rows:GRID.rows.map(r=>r.excel_row),
    order:colOrder.map(ci=>GRID.columns[ci].target)};   // סדר עמודות לייצוא
}
async function revalidate(){
  const res=await post('/grid/validate',collect()); if(!res)return;
  GRID.rows=res.rows; render();
  const o=overall();
  flash(o.invalid===0?'ok':'err', o.invalid===0?'✓ כל השורות תקינות — אפשר לייצר קובץ טעינה.':
        'נותרו '+o.invalid+' שורות עם שגיאות לתיקון.');
}
async function generate(){
  const res=await post('/grid/generate',collect()); if(!res)return;
  if(res.rows){ GRID.rows=res.rows; GRID.server_valid=res.server_valid; GRID.overflow=res.overflow; render(); }
  let html='';
  if(res.valid>0){ html+='<a class="dl" href="/download/'+res.run_id+'/load">⬇ הורדת קובץ הטעינה ('+esc(res.load_name)+')</a>';
    html+='<a class="dl rep" href="/download/'+res.run_id+'/report">⬇ דוח</a>'; }
  if(res.invalid>0) html+='<a class="dl rej" href="/download/'+res.run_id+'/rejected">⬇ שורות פסולות ('+res.invalid+')</a>';
  $('dlarea').innerHTML=html;
  flash(res.invalid>0?'err':'ok',
    res.invalid>0?('נוצר קובץ טעינה עם '+res.valid+' שורות תקינות. '+res.invalid+' שורות שגויות לא נכללו.'):
                  ('✓ נוצר קובץ טעינה מלא עם '+res.valid+' שורות. לחץ להורדה.'));
}
async function post(url,body){
  try{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const j=await r.json(); if(!r.ok||j.error){flash('err','שגיאה: '+(j.error||r.status));return null;} return j;
  }catch(e){flash('err','תקלה בתקשורת עם השרת: '+e);return null;}
}
let ft=null;
function flash(kind,text){const box=document.createElement('div');box.className='msg '+(kind==='ok'?'ok':'err');box.textContent=text;
  $('messages').prepend(box);clearTimeout(ft);ft=setTimeout(()=>{if(box.parentNode)box.remove();},6000);}

if(GRID.mode==='errors') $('onlyerr').checked=true;
renderBanner(); render();
</script></body></html>
"""


# ---------------------------------------------------------------------------
# נתיבים
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template_string(UPLOAD, screens=core.available_screens(), error=None)


@app.route("/process", methods=["POST"])
def process():
    screen = (request.form.get("screen") or "").strip()
    sheet = (request.form.get("sheet") or "").strip() or None
    header_row = (request.form.get("header_row") or "").strip()
    header_row = int(header_row) if header_row.isdigit() else None
    upload = request.files.get("file")

    if not upload or not upload.filename:
        return _upload_error("לא נבחר קובץ אקסל.")
    if not upload.filename.lower().endswith(".xlsx"):
        return _upload_error("יש להעלות קובץ בפורמט .xlsx בלבד.")

    try:
        mapping = core.load_mapping(screen)
        df = core.read_excel(
            io.BytesIO(upload.read()), sheet,
            header_row=header_row if header_row is not None else mapping.get("header_row"),
            expected_sources=core._expected_sources(mapping),
        )
        resolved = core.build_column_lookup(df, mapping["columns"])
        rows_out = core.evaluate_grid(mapping, core.rows_from_dataframe(df, mapping, resolved))
    except core.UserError as e:
        return _upload_error(str(e))
    except Exception as e:  # noqa: BLE001
        return _upload_error(f"שגיאה בלתי צפויה בעיבוד הקובץ:\n{e}")

    key_fields = mapping.get("key_fields") or []
    valid_rows = [r for r in rows_out if r["valid"]]
    invalid_rows = [r for r in rows_out if not r["valid"]]
    total = len(rows_out)

    if total <= FULL_GRID_LIMIT:
        # קובץ קטן — כל השורות בטבלה
        displayed, server_valid = rows_out, []
        reserved, overflow_items = set(), []
    else:
        # קובץ גדול — מציגים רק שגויות; התקינות נשמרות בשרת
        displayed = invalid_rows[:DISPLAY_CAP]
        server_valid = core.grid_valid_records(valid_rows)
        reserved = {core.row_key(r["cells"], key_fields) for r in valid_rows} if key_fields else set()
        overflow_items = [
            (r["excel_row"], {c["target"]: c["value"] for c in r["cells"]}, _first_reason(r["cells"]))
            for r in invalid_rows[DISPLAY_CAP:]
        ]

    run_id = _store_run(screen, server_valid, reserved, overflow_items)
    warnings, warn_count = _sample_warnings(mapping, core.grid_valid_records(valid_rows))

    payload = {
        "screen": screen, "run_id": run_id, "interface": mapping.get("interface_name"),
        "mode": "errors" if total > FULL_GRID_LIMIT else "all",
        "columns": _columns_meta(mapping), "key_fields": key_fields,
        "rows": displayed, "server_valid": len(server_valid),
        "overflow": len(overflow_items), "total": total,
        "warnings": warnings, "warn_count": warn_count,
    }
    return render_template_string(GRID, screen=screen, grid=payload)


@app.route("/grid/validate", methods=["POST"])
def grid_validate():
    data = request.get_json(silent=True) or {}
    try:
        mapping = core.load_mapping((data.get("screen") or "").strip())
        run = RUNS.get(data.get("run_id"))
        reserved = run["reserved"] if run else set()
        rows_out = core.evaluate_grid(
            mapping, data.get("rows") or [], reserved_keys=reserved,
            excel_rows=data.get("excel_rows"),
        )
    except core.UserError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"שגיאה בבדיקה: {e}"), 400
    return jsonify(rows=rows_out)


@app.route("/grid/generate", methods=["POST"])
def grid_generate():
    data = request.get_json(silent=True) or {}
    screen = (data.get("screen") or "").strip()
    try:
        mapping = core.load_mapping(screen)
        run = RUNS.get(data.get("run_id")) or {"valid": [], "reserved": set(), "overflow": []}
        rows_out = core.evaluate_grid(
            mapping, data.get("rows") or [], reserved_keys=run["reserved"],
            excel_rows=data.get("excel_rows"),
        )
    except core.UserError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"שגיאה בהפקה: {e}"), 400

    now_valid = [r for r in rows_out if r["valid"]]
    still_invalid = [r for r in rows_out if not r["valid"]]
    valid_records = run["valid"] + core.grid_valid_records(now_valid)

    # סדר עמודות מבוקש (אם המשתמש סידר מחדש בטבלה) — חל על קובץ הטעינה ועל rejected
    order = data.get("order")
    export_mapping = mapping
    if order:
        valid_records, export_mapping = core.reorder_for_export(valid_records, mapping, order)

    run_id = uuid.uuid4().hex
    run_dir = os.path.join(WEB_OUTPUT, run_id)
    os.makedirs(run_dir, exist_ok=True)

    load_name = f"{screen}_load.{core.load_file_extension(export_mapping)}"
    if valid_records:
        content = core.build_load_content(valid_records, export_mapping)
        with open(os.path.join(run_dir, load_name), "wb") as f:
            f.write(core.load_content_bytes(content, export_mapping))

    rejected_items = [
        (r["excel_row"], {c["target"]: c["value"] for c in r["cells"]}, _first_reason(r["cells"]))
        for r in still_invalid
    ] + run["overflow"]
    if rejected_items:
        _rejected_df(export_mapping, rejected_items).to_excel(
            os.path.join(run_dir, f"{screen}_rejected.xlsx"), index=False, engine="openpyxl")

    warnings, warn_count = _sample_warnings(mapping, valid_records)
    report = core.build_report(
        screen, mapping, len(valid_records) + len(rejected_items), valid_records,
        [{"reason": r[2]} for r in rejected_items], warnings,
        load_name if valid_records else None,
        f"{screen}_rejected.xlsx" if rejected_items else None, False)
    with open(os.path.join(run_dir, f"{screen}_report.txt"), "w", encoding="utf-8") as f:
        f.write(report)

    return jsonify(
        run_id=run_id, load_name=load_name,
        valid=len(valid_records), invalid=len(rejected_items),
        rows=rows_out, server_valid=len(run["valid"]), overflow=len(run["overflow"]),
    )


@app.route("/download/<run_id>/<kind>")
def download(run_id, kind):
    if not _RUN_ID_RE.match(run_id):
        abort(404)
    run_dir = os.path.join(WEB_OUTPUT, run_id)
    if not os.path.isdir(run_dir):
        abort(404)
    suffix = {"load": "_load.", "rejected": "_rejected.xlsx", "report": "_report.txt"}.get(kind)
    if not suffix:
        abort(404)
    for fname in os.listdir(run_dir):
        if suffix in fname or fname.endswith(suffix):
            return send_from_directory(run_dir, fname, as_attachment=True)
    abort(404)


def _upload_error(msg):
    return render_template_string(UPLOAD, screens=core.available_screens(), error=msg)


if __name__ == "__main__":
    os.makedirs(WEB_OUTPUT, exist_ok=True)
    print("=" * 56)
    print("  ממשק הכנת קבצי טעינה לפריוריטי פועל")
    print("  פתח בדפדפן:  http://127.0.0.1:5000")
    print("  לעצירה: Ctrl+C")
    print("=" * 56)
    app.run(host="127.0.0.1", port=5000, debug=False)
