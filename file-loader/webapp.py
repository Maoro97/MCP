# -*- coding: utf-8 -*-
"""
webapp.py — ממשק וובי מקומי להכנת קבצי טעינה לפריוריטי

מפעיל שרת מקומי (Flask). מעלים קובץ אקסל, בוחרים מסך יעד, ומקבלים
**טבלת טעינה אינטראקטיבית**: הנתונים מוצגים כטבלה, תאים שגויים נצבעים
באדום עם סיבת השגיאה, וניתן לתקן אותם במקום, לבדוק מחדש, ולייצר את
קובץ הטעינה — הכל מקומית, בלי שהנתונים יוצאים מהמחשב.

הפעלה:
    python webapp.py
ואז בדפדפן:  http://127.0.0.1:5000
"""

import io
import os
import re
import uuid

import pandas as pd
from flask import (
    Flask,
    request,
    jsonify,
    render_template_string,
    send_from_directory,
    abort,
)

import main as core

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # מגבלת העלאה: 50MB

WEB_OUTPUT = os.path.join(core.OUTPUT_DIR, "web")
_RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")


# ---------------------------------------------------------------------------
# עוזרים
# ---------------------------------------------------------------------------
def _columns_meta(mapping):
    """מטא-דאטה של העמודות לצד הלקוח (מה עורכים, מה קבוע)."""
    meta = []
    for col in mapping["columns"]:
        meta.append({
            "target": col["target"],
            "source": col.get("source"),
            "constant": col.get("source") is None,
            "type": col.get("type", "text"),
        })
    return meta


def _grid_payload(screen, mapping, rows_out):
    valid = sum(1 for r in rows_out if r["valid"])
    warnings = core.check_encoding(
        core.grid_valid_records(rows_out), mapping["columns"],
        mapping.get("encoding", "windows-1255"),
    )
    return {
        "screen": screen,
        "columns": _columns_meta(mapping),
        "key_fields": mapping.get("key_fields") or [],
        "interface": mapping.get("interface_name"),
        "rows": rows_out,
        "valid": valid,
        "invalid": len(rows_out) - valid,
        "total": len(rows_out),
        "warnings": warnings,
    }


def _grid_rejected_df(mapping, rows_out):
    """DataFrame של השורות הפסולות מטבלת הטעינה (ערכי היעד + סיבת פסילה)."""
    targets = [c["target"] for c in mapping["columns"]]
    data = []
    for r in rows_out:
        if r["valid"]:
            continue
        row = {c["target"]: c["value"] for c in r["cells"]}
        reasons = [c["error"] for c in r["cells"] if c["error"]]
        row["שורה"] = r["excel_row"]
        row["סיבת פסילה"] = reasons[0] if reasons else ""
        data.append(row)
    return pd.DataFrame(data, columns=targets + ["שורה", "סיבת פסילה"])


# ---------------------------------------------------------------------------
# עמוד ההעלאה
# ---------------------------------------------------------------------------
UPLOAD = """
<!doctype html>
<html lang="he" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>הכנת קובץ טעינה — Priority ERP</title>
<style>
  :root{--bg:#f4f6fb;--card:#fff;--line:#e3e8f0;--ink:#1e2a3a;--muted:#6b7a90;--blue:#2563eb;--green:#16a34a;--red:#dc2626;}
  *{box-sizing:border-box}
  body{margin:0;font-family:"Segoe UI",Arial,sans-serif;background:var(--bg);color:var(--ink);line-height:1.6}
  .wrap{max-width:760px;margin:0 auto;padding:30px 18px 60px}
  h1{font-size:24px;margin:0 0 4px}
  header p{color:var(--muted);margin:0 0 22px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px;margin-bottom:18px}
  label{display:block;font-weight:600;margin:0 0 6px}
  select,input[type=text]{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:9px;font-size:15px;font-family:inherit;background:#fff}
  .row{display:flex;gap:16px;flex-wrap:wrap}
  .row>div{flex:1;min-width:220px;margin-bottom:16px}
  .drop{border:2px dashed #c3ccdb;border-radius:12px;padding:26px;text-align:center;cursor:pointer;background:#fafbfe;transition:.15s}
  .drop.over{border-color:var(--blue);background:#eef3ff}
  .drop b{color:var(--blue)} .drop small{display:block;color:var(--muted);margin-top:6px}
  .fname{margin-top:10px;font-weight:600;color:var(--green)}
  button{background:var(--blue);color:#fff;border:0;border-radius:10px;padding:12px 26px;font-size:16px;font-weight:600;cursor:pointer;margin-top:10px}
  button:hover{background:#1d4ed8}
  .muted{color:var(--muted);font-size:14px}
  .err{background:#fef2f2;border:1px solid #fecaca;color:#991b1b;border-radius:12px;padding:16px 18px;white-space:pre-wrap}
  code{background:#eef1f7;padding:2px 6px;border-radius:5px}
  a.back{color:var(--blue);text-decoration:none;font-weight:600}
</style></head><body><div class="wrap">
  <header><h1>הכנת קובץ טעינה ל-Priority ERP</h1>
  <p>העלה קובץ אקסל ובחר מסך יעד — תקבל טבלת טעינה לתיקון שגיאות לפני הפקת הקובץ.</p></header>
  {% if error %}
    <div class="card"><div class="err">❌ {{ error }}</div>
      <p style="margin-top:14px"><a class="back" href="/">→ חזרה</a></p></div>
  {% else %}
    <form class="card" method="post" action="/process" enctype="multipart/form-data">
      {% if not screens %}
        <div class="err">לא נמצאו קבצי מיפוי בתיקיית <code>mappings/</code>.</div>
      {% else %}
      <div class="row">
        <div><label for="screen">מסך יעד</label>
          <select id="screen" name="screen">
            {% for s in screens %}<option value="{{ s }}">{{ s }}</option>{% endfor %}
          </select></div>
        <div><label for="sheet">שם הגיליון (רשות)</label>
          <input type="text" id="sheet" name="sheet" placeholder="ברירת מחדל: הגיליון הראשון"></div>
      </div>
      <label>קובץ האקסל</label>
      <div class="drop" id="drop"><b>גרור לכאן קובץ</b> או לחץ לבחירה
        <small>קבצי .xlsx בלבד</small>
        <input type="file" id="file" name="file" accept=".xlsx" hidden required>
        <div class="fname" id="fname"></div></div>
      <button type="submit">טען לטבלה</button>
      {% endif %}
    </form>
    <p class="muted">הכל רץ מקומית על המחשב שלך — הקובץ לא נשלח לשום שרת חיצוני.</p>
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
# עמוד טבלת הטעינה האינטראקטיבית
# ---------------------------------------------------------------------------
GRID = """
<!doctype html>
<html lang="he" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>טבלת טעינה — {{ screen }}</title>
<style>
  :root{--bg:#f4f6fb;--card:#fff;--line:#e3e8f0;--ink:#1e2a3a;--muted:#6b7a90;--blue:#2563eb;--green:#16a34a;--red:#dc2626;--amber:#d97706;}
  *{box-sizing:border-box}
  body{margin:0;font-family:"Segoe UI",Arial,sans-serif;background:var(--bg);color:var(--ink)}
  .wrap{max-width:1300px;margin:0 auto;padding:20px 16px 80px}
  h1{font-size:21px;margin:0 0 2px} .sub{color:var(--muted);font-size:14px;margin:0 0 16px}
  .bar{background:var(--bg);padding:10px 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap;border-bottom:1px solid var(--line);margin-bottom:14px}
  .pill{border-radius:999px;padding:6px 14px;font-weight:700;font-size:14px}
  .pill.tot{background:#eef2f7;color:#334155} .pill.ok{background:#dcfce7;color:#166534} .pill.bad{background:#fee2e2;color:#991b1b}
  button{border:0;border-radius:9px;padding:10px 18px;font-size:15px;font-weight:600;cursor:pointer}
  .b-check{background:#475569;color:#fff} .b-gen{background:var(--green);color:#fff} .b-check:hover{background:#334155} .b-gen:hover{background:#15803d}
  .spacer{flex:1}
  a.back{color:var(--blue);text-decoration:none;font-weight:600;font-size:14px}
  .tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:12px;background:#fff}
  table{border-collapse:collapse;width:100%;font-size:14px}
  th,td{border-bottom:1px solid var(--line);border-left:1px solid var(--line);padding:0;text-align:right;white-space:nowrap}
  th{background:#f7f9fc;padding:8px 10px;position:sticky;top:0;z-index:2}
  th .tgt{font-weight:700} th .src{display:block;font-weight:400;color:var(--muted);font-size:12px}
  th.rownum,td.rownum{background:#f1f5f9;color:#64748b;text-align:center;font-size:12px;position:sticky;right:0;z-index:1;min-width:44px;padding:6px}
  td input{border:0;background:transparent;width:100%;min-width:110px;padding:8px 10px;font:inherit;color:inherit;outline:none}
  td.bad{background:#fef2f2} td.bad input{color:#b91c1c;font-weight:600}
  td.bad{position:relative} td.bad::after{content:"!";position:absolute;top:2px;left:4px;color:#dc2626;font-weight:800;font-size:11px}
  td input:focus{background:#eef3ff;box-shadow:inset 0 0 0 2px var(--blue)}
  td.const input{background:#f8fafc;color:#64748b}
  tr.rowbad td.rownum{background:#fee2e2;color:#991b1b;font-weight:700}
  .legend{display:flex;gap:16px;color:var(--muted);font-size:13px;margin:10px 2px}
  .legend i{display:inline-block;width:13px;height:13px;border-radius:3px;vertical-align:middle;margin-left:5px}
  .msg{border-radius:10px;padding:12px 16px;margin:12px 0;font-weight:600}
  .msg.ok{background:#dcfce7;color:#166534} .msg.warnbox{background:#fffbeb;color:#92400e;border:1px solid #fde68a;font-weight:500}
  .msg.err{background:#fef2f2;color:#991b1b}
  .dl{display:inline-block;background:var(--green);color:#fff;text-decoration:none;border-radius:9px;padding:10px 18px;font-weight:600;margin:6px 8px 6px 0}
  .dl.rej{background:var(--red)} .dl.rep{background:#475569}
  .hint{color:var(--muted);font-size:13px}
</style></head><body><div class="wrap">
  <h1>טבלת טעינה — מסך {{ screen }}</h1>
  <p class="sub">תקן תאים אדומים (רחף לראות את הסיבה), לחץ <b>בדוק מחדש</b>, ואז <b>צור קובץ טעינה</b>.</p>

  <div class="bar">
    <span class="pill tot" id="p-tot">סה״כ 0</span>
    <span class="pill ok" id="p-ok">תקינות 0</span>
    <span class="pill bad" id="p-bad">שגויות 0</span>
    <button class="b-check" onclick="revalidate()">🔄 בדוק מחדש</button>
    <button class="b-gen" onclick="generate()">⬇ צור קובץ טעינה</button>
    <span class="spacer"></span>
    <a class="back" href="/">→ קובץ חדש</a>
  </div>

  <div id="messages"></div>
  <div class="legend">
    <span><i style="background:#fef2f2;border:1px solid #fecaca"></i>תא שגוי לתיקון</span>
    <span><i style="background:#f8fafc;border:1px solid #e3e8f0"></i>ערך קבוע (לא לעריכה)</span>
    <span class="hint">התאריך תמיד בפורמט dd/mm/yy</span>
  </div>

  <div class="tablewrap"><table id="grid"></table></div>
  <p class="hint" id="dlarea"></p>

<script>
const GRID = {{ grid|tojson }};
const $ = id => document.getElementById(id);

function render(){
  const cols = GRID.columns, rows = GRID.rows;
  let h = '<thead><tr><th class="rownum">#</th>';
  for(const c of cols){
    h += '<th><span class="tgt">'+esc(c.target)+'</span><span class="src">'+
         (c.constant ? 'ערך קבוע' : esc(c.source||''))+'</span></th>';
  }
  h += '</tr></thead><tbody>';
  rows.forEach((r,ri)=>{
    h += '<tr class="'+(r.valid?'':'rowbad')+'"><td class="rownum">'+r.excel_row+'</td>';
    r.cells.forEach((cell,ci)=>{
      const c = cols[ci];
      const cls = (cell.error?'bad ':'')+(c.constant?'const':'');
      const title = cell.error ? ' title="'+esc(cell.error)+'"' : '';
      const ro = c.constant ? ' readonly' : '';
      h += '<td class="'+cls+'"'+title+'><input id="c_'+ri+'_'+ci+'" value="'+esc(cell.value)+'"'+ro+'></td>';
    });
    h += '</tr>';
  });
  h += '</tbody>';
  $('grid').innerHTML = h;
  $('p-tot').textContent = 'סה״כ '+GRID.total;
  $('p-ok').textContent  = 'תקינות '+GRID.valid;
  $('p-bad').textContent = 'שגויות '+GRID.invalid;
  renderMessages();
}

function renderMessages(){
  let m = '';
  if(GRID.warnings && GRID.warnings.length){
    m += '<div class="msg warnbox">⚠ אזהרות קידוד ('+GRID.warnings.length+'): תווים שלא ניתנים ל-windows-1255 יוחלפו ב-?. '+
         esc(GRID.warnings.slice(0,3).join(' | '))+(GRID.warnings.length>3?' ...':'')+'</div>';
  }
  $('messages').innerHTML = m;
}

function collect(){
  const rows = [];
  GRID.rows.forEach((r,ri)=>{
    const obj = {};
    GRID.columns.forEach((c,ci)=>{
      const el = $('c_'+ri+'_'+ci);
      obj[c.target] = c.constant ? r.cells[ci].value : (el ? el.value : '');
    });
    rows.push(obj);
  });
  return rows;
}

async function revalidate(){
  const res = await post('/grid/validate', {screen:GRID.screen, rows:collect()});
  if(!res) return;
  GRID.rows=res.rows; GRID.valid=res.valid; GRID.invalid=res.invalid;
  GRID.total=res.total; GRID.warnings=res.warnings;
  render();
  flash(res.invalid===0 ? 'ok' : 'err',
        res.invalid===0 ? '✓ כל השורות תקינות — אפשר לייצר קובץ טעינה.'
                        : 'נותרו '+res.invalid+' שורות עם שגיאות לתיקון.');
}

async function generate(){
  const res = await post('/grid/generate', {screen:GRID.screen, rows:collect()});
  if(!res) return;
  GRID.rows=res.rows; GRID.valid=res.valid; GRID.invalid=res.invalid;
  GRID.total=res.total; GRID.warnings=res.warnings; render();
  let html = '';
  if(res.valid>0){
    html += '<a class="dl" href="/download/'+res.run_id+'/load">⬇ הורדת קובץ הטעינה ('+esc(res.load_name)+')</a>';
    html += '<a class="dl rep" href="/download/'+res.run_id+'/report">⬇ דוח</a>';
  }
  if(res.invalid>0){
    html += '<a class="dl rej" href="/download/'+res.run_id+'/rejected">⬇ שורות פסולות ('+res.invalid+')</a>';
  }
  $('dlarea').innerHTML = html;
  if(res.invalid>0)
    flash('err','נוצר קובץ טעינה עם '+res.valid+' שורות תקינות בלבד. '+res.invalid+' שורות שגויות לא נכללו — תקן אותן והפק שוב.');
  else
    flash('ok','✓ נוצר קובץ טעינה מלא עם '+res.valid+' שורות. לחץ להורדה.');
}

async function post(url, body){
  try{
    const r = await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const j = await r.json();
    if(!r.ok || j.error){ flash('err','שגיאה: '+(j.error||r.status)); return null; }
    return j;
  }catch(e){ flash('err','תקלה בתקשורת עם השרת: '+e); return null; }
}

let flashTimer=null;
function flash(kind,text){
  const box=document.createElement('div'); box.className='msg '+(kind==='ok'?'ok':'err'); box.textContent=text;
  const cur=$('messages'); cur.prepend(box);
  clearTimeout(flashTimer); flashTimer=setTimeout(()=>{ if(box.parentNode) box.remove(); },6000);
}
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

render();
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
    upload = request.files.get("file")

    if not upload or not upload.filename:
        return _upload_error("לא נבחר קובץ אקסל.")
    if not upload.filename.lower().endswith(".xlsx"):
        return _upload_error("יש להעלות קובץ בפורמט .xlsx בלבד.")

    try:
        mapping = core.load_mapping(screen)
        df = core.read_excel(io.BytesIO(upload.read()), sheet)
        resolved = core.build_column_lookup(df, mapping["columns"])
        rows_out = core.evaluate_grid(mapping, core.rows_from_dataframe(df, mapping, resolved))
    except core.UserError as e:
        return _upload_error(str(e))
    except Exception as e:  # noqa: BLE001
        return _upload_error(f"שגיאה בלתי צפויה בעיבוד הקובץ:\n{e}")

    payload = _grid_payload(screen, mapping, rows_out)
    return render_template_string(GRID, screen=screen, grid=payload)


@app.route("/grid/validate", methods=["POST"])
def grid_validate():
    data = request.get_json(silent=True) or {}
    try:
        mapping = core.load_mapping((data.get("screen") or "").strip())
        rows_out = core.evaluate_grid(mapping, data.get("rows") or [])
    except core.UserError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"שגיאה בבדיקה: {e}"), 400
    return jsonify(_grid_payload(data.get("screen"), mapping, rows_out))


@app.route("/grid/generate", methods=["POST"])
def grid_generate():
    data = request.get_json(silent=True) or {}
    screen = (data.get("screen") or "").strip()
    try:
        mapping = core.load_mapping(screen)
        rows_out = core.evaluate_grid(mapping, data.get("rows") or [])
    except core.UserError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"שגיאה בהפקה: {e}"), 400

    valid_records = core.grid_valid_records(rows_out)
    payload = _grid_payload(screen, mapping, rows_out)

    run_id = uuid.uuid4().hex
    run_dir = os.path.join(WEB_OUTPUT, run_id)
    os.makedirs(run_dir, exist_ok=True)

    load_name = f"{screen}_load.{core.load_file_extension(mapping)}"
    if valid_records:
        content = core.build_load_content(valid_records, mapping)
        with open(os.path.join(run_dir, load_name), "wb") as f:
            f.write(core.load_content_bytes(content, mapping))

    invalid = payload["invalid"]
    if invalid:
        _grid_rejected_df(mapping, rows_out).to_excel(
            os.path.join(run_dir, f"{screen}_rejected.xlsx"), index=False, engine="openpyxl")

    # דוח (משתמש בליבת הדוח של ה-CLI)
    rejected_stub = [{"reason": next((c["error"] for c in r["cells"] if c["error"]), "")}
                     for r in rows_out if not r["valid"]]
    report = core.build_report(
        screen, mapping, payload["total"], valid_records, rejected_stub,
        payload["warnings"], load_name if valid_records else None,
        f"{screen}_rejected.xlsx" if invalid else None, False)
    with open(os.path.join(run_dir, f"{screen}_report.txt"), "w", encoding="utf-8") as f:
        f.write(report)

    payload.update(run_id=run_id, load_name=load_name)
    return jsonify(payload)


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
