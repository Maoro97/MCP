# -*- coding: utf-8 -*-
"""
webapp.py — ממשק וובי מקומי להכנת קבצי טעינה לפריוריטי

מפעיל שרת מקומי (Flask) שמאפשר להעלות קובץ אקסל דרך הדפדפן, לבחור מסך יעד,
ולקבל בחזרה את קובץ הטעינה + קובץ השורות הפסולות + דוח — בלי שהנתונים יוצאים מהמחשב.

הפעלה:
    python webapp.py
ואז לפתוח בדפדפן:  http://127.0.0.1:5000

הממשק עוטף את אותה ליבת עיבוד של ה-CLI (main.prepare), כך שהתוצאה זהה.
"""

import io
import os
import re
import uuid
from collections import Counter

from flask import (
    Flask,
    request,
    render_template_string,
    send_from_directory,
    abort,
)

import main as core

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # מגבלת גודל העלאה: 50MB

# תיקיית עבודה לקבצים שנוצרים בממשק הוובי (כל ריצה בתת-תיקייה ייחודית)
WEB_OUTPUT = os.path.join(core.OUTPUT_DIR, "web")
_RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")


# ---------------------------------------------------------------------------
# תבנית HTML (RTL, עברית) — מוטמעת בקובץ כדי לשמור על פרויקט קומפקטי
# ---------------------------------------------------------------------------
PAGE = """
<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>הכנת קובץ טעינה — Priority ERP</title>
<style>
  :root { --bg:#f4f6fb; --card:#fff; --line:#e3e8f0; --ink:#1e2a3a;
          --muted:#6b7a90; --blue:#2563eb; --green:#16a34a; --red:#dc2626;
          --amber:#d97706; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:"Segoe UI",Arial,sans-serif; background:var(--bg);
         color:var(--ink); line-height:1.6; }
  .wrap { max-width:860px; margin:0 auto; padding:28px 18px 60px; }
  header h1 { font-size:24px; margin:0 0 4px; }
  header p { color:var(--muted); margin:0 0 22px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px;
          padding:22px; margin-bottom:20px; box-shadow:0 1px 3px rgba(20,40,80,.04); }
  label { display:block; font-weight:600; margin:0 0 6px; }
  select, input[type=text] { width:100%; padding:10px 12px; border:1px solid var(--line);
          border-radius:9px; font-size:15px; font-family:inherit; background:#fff; }
  .row { display:flex; gap:16px; flex-wrap:wrap; }
  .row > div { flex:1; min-width:220px; margin-bottom:16px; }
  .drop { border:2px dashed #c3ccdb; border-radius:12px; padding:26px; text-align:center;
          cursor:pointer; transition:.15s; background:#fafbfe; }
  .drop.over { border-color:var(--blue); background:#eef3ff; }
  .drop b { color:var(--blue); }
  .drop small { display:block; color:var(--muted); margin-top:6px; }
  .fname { margin-top:10px; font-weight:600; color:var(--green); }
  .check { display:flex; align-items:center; gap:8px; margin:6px 0 0; font-weight:500; }
  .check input { width:18px; height:18px; }
  button { background:var(--blue); color:#fff; border:0; border-radius:10px;
           padding:12px 26px; font-size:16px; font-weight:600; cursor:pointer;
           margin-top:10px; }
  button:hover { background:#1d4ed8; }
  .stats { display:flex; gap:12px; flex-wrap:wrap; margin:0 0 18px; }
  .stat { flex:1; min-width:120px; text-align:center; border:1px solid var(--line);
          border-radius:12px; padding:14px; }
  .stat .n { font-size:30px; font-weight:700; }
  .stat.read .n{color:var(--ink);} .stat.ok .n{color:var(--green);}
  .stat.bad .n{color:var(--red);}
  .dl { display:inline-block; background:var(--green); color:#fff; text-decoration:none;
        border-radius:10px; padding:11px 20px; font-weight:600; margin:6px 8px 6px 0; }
  .dl.rej { background:var(--red); }
  .dl.rep { background:#475569; }
  table { width:100%; border-collapse:collapse; margin-top:10px; font-size:14px; }
  th,td { text-align:right; padding:8px 10px; border-bottom:1px solid var(--line); }
  th { background:#f7f9fc; }
  .err { background:#fef2f2; border:1px solid #fecaca; color:#991b1b; border-radius:12px;
         padding:16px 18px; white-space:pre-wrap; }
  .warn { background:#fffbeb; border:1px solid #fde68a; color:#92400e; border-radius:10px;
          padding:10px 14px; margin-top:6px; font-size:14px; }
  .muted { color:var(--muted); font-size:14px; }
  h2 { font-size:18px; margin:22px 0 8px; }
  a.back { color:var(--blue); text-decoration:none; font-weight:600; }
  code { background:#eef1f7; padding:2px 6px; border-radius:5px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>הכנת קובץ טעינה ל-Priority ERP</h1>
    <p>העלה קובץ אקסל, בחר מסך יעד, וקבל קובץ טעינה מוכן ל-Interface (File Load).</p>
  </header>

  {% if error %}
    <div class="card"><div class="err">❌ {{ error }}</div>
      <p style="margin-top:14px"><a class="back" href="/">→ חזרה</a></p>
    </div>
  {% elif result %}
    {{ result|safe }}
  {% else %}
    <form class="card" method="post" action="/process" enctype="multipart/form-data">
      {% if not screens %}
        <div class="err">לא נמצאו קבצי מיפוי בתיקיית <code>mappings/</code>.</div>
      {% else %}
      <div class="row">
        <div>
          <label for="screen">מסך יעד</label>
          <select id="screen" name="screen">
            {% for s in screens %}<option value="{{ s }}">{{ s }}</option>{% endfor %}
          </select>
        </div>
        <div>
          <label for="sheet">שם הגיליון (רשות)</label>
          <input type="text" id="sheet" name="sheet" placeholder="ברירת מחדל: הגיליון הראשון">
        </div>
      </div>

      <label>קובץ האקסל</label>
      <div class="drop" id="drop">
        <b>גרור לכאן קובץ</b> או לחץ לבחירה
        <small>קבצי .xlsx בלבד</small>
        <input type="file" id="file" name="file" accept=".xlsx" hidden required>
        <div class="fname" id="fname"></div>
      </div>

      <label class="check"><input type="checkbox" name="dry_run" value="1">
        ולידציה בלבד (dry-run) — בלי לייצר קובץ טעינה</label>

      <button type="submit">עבד את הקובץ</button>
      {% endif %}
    </form>
    <p class="muted">הכל רץ מקומית על המחשב שלך — הקובץ לא נשלח לשום שרת חיצוני.</p>
  {% endif %}
</div>

<script>
  const drop=document.getElementById('drop'), file=document.getElementById('file'),
        fname=document.getElementById('fname');
  if (drop) {
    drop.addEventListener('click',()=>file.click());
    file.addEventListener('change',()=>{ if(file.files[0]) fname.textContent='📄 '+file.files[0].name; });
    ['dragover','dragenter'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add('over');}));
    ['dragleave','drop'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove('over');}));
    drop.addEventListener('drop',ev=>{ file.files=ev.dataTransfer.files;
       if(file.files[0]) fname.textContent='📄 '+file.files[0].name; });
  }
</script>
</body>
</html>
"""

RESULT = """
<div class="card">
  <div class="stats">
    <div class="stat read"><div class="n">{{ total }}</div>שורות שנקראו</div>
    <div class="stat ok"><div class="n">{{ valid }}</div>שורות תקינות</div>
    <div class="stat bad"><div class="n">{{ rejected }}</div>שורות שנפסלו</div>
  </div>

  {% if dry_run %}
    <p class="muted">מצב ולידציה בלבד (dry-run) — לא נוצר קובץ טעינה.</p>
  {% elif valid > 0 %}
    <a class="dl" href="/download/{{ run_id }}/load">⬇ הורדת קובץ הטעינה ({{ load_name }})</a>
  {% else %}
    <p class="muted">אין שורות תקינות — לא נוצר קובץ טעינה.</p>
  {% endif %}
  {% if rejected > 0 %}
    <a class="dl rej" href="/download/{{ run_id }}/rejected">⬇ שורות פסולות לתיקון (xlsx)</a>
  {% endif %}
  <a class="dl rep" href="/download/{{ run_id }}/report">⬇ דוח מלא</a>
</div>

{% if top_errors %}
<div class="card">
  <h2>פירוט השגיאות הנפוצות</h2>
  <table><tr><th>#</th><th>סוג השגיאה</th><th>מספר שורות</th></tr>
  {% for cat, cnt in top_errors %}<tr><td>{{ loop.index }}</td><td>{{ cat }}</td><td>{{ cnt }}</td></tr>{% endfor %}
  </table>
</div>
{% endif %}

{% if warnings %}
<div class="card">
  <h2>אזהרות קידוד ({{ warnings|length }})</h2>
  <p class="muted">תווים שלא ניתנים לקידוד היעד יוחלפו ב-<code>?</code> בקובץ הטעינה.</p>
  {% for w in warnings[:15] %}<div class="warn">⚠ {{ w }}</div>{% endfor %}
  {% if warnings|length > 15 %}<p class="muted">... ועוד {{ warnings|length - 15 }} (ראו בדוח).</p>{% endif %}
</div>
{% endif %}

{% if rejected_rows %}
<div class="card">
  <h2>דוגמת שורות פסולות</h2>
  <table><tr><th>שורה במקור</th><th>סיבת פסילה</th></tr>
  {% for r in rejected_rows %}<tr><td>{{ r[0] }}</td><td>{{ r[1] }}</td></tr>{% endfor %}
  </table>
  {% if rejected > rejected_rows|length %}<p class="muted">מוצגות {{ rejected_rows|length }} מתוך {{ rejected }} — הרשימה המלאה בקובץ ה-xlsx.</p>{% endif %}
</div>
{% endif %}

<p><a class="back" href="/">→ עיבוד קובץ נוסף</a></p>
"""


@app.route("/")
def index():
    return render_template_string(PAGE, screens=core.available_screens(),
                                  result=None, error=None)


@app.route("/process", methods=["POST"])
def process():
    screen = (request.form.get("screen") or "").strip()
    sheet = (request.form.get("sheet") or "").strip() or None
    dry_run = request.form.get("dry_run") == "1"
    upload = request.files.get("file")

    if not upload or not upload.filename:
        return _error("לא נבחר קובץ אקסל.")
    if not upload.filename.lower().endswith(".xlsx"):
        return _error("יש להעלות קובץ בפורמט .xlsx בלבד.")

    try:
        data = io.BytesIO(upload.read())
        res = core.prepare(screen, data, sheet)
    except core.UserError as e:
        return _error(str(e))
    except Exception as e:  # noqa: BLE001 — הודעה ידידותית במקום stack trace
        return _error(f"שגיאה בלתי צפויה בעיבוד הקובץ:\n{e}")

    mapping = res["mapping"]
    valid, rejected = res["valid"], res["rejected"]

    # שמירת הקבצים שנוצרו בתת-תיקייה ייחודית לריצה
    run_id = uuid.uuid4().hex
    run_dir = os.path.join(WEB_OUTPUT, run_id)
    os.makedirs(run_dir, exist_ok=True)

    load_name = f"{screen}_load.{core.load_file_extension(mapping)}"
    if not dry_run and valid:
        content = core.build_load_content(valid, mapping)
        with open(os.path.join(run_dir, load_name), "wb") as f:
            f.write(core.load_content_bytes(content, mapping))

    if rejected:
        core.build_rejected_df(rejected, res["df"]).to_excel(
            os.path.join(run_dir, f"{screen}_rejected.xlsx"),
            index=False, engine="openpyxl",
        )

    # דוח טקסט (זהה ל-CLI)
    report = core.build_report(
        screen, mapping, res["total"], valid, rejected, res["warnings"],
        None if dry_run else load_name, f"{screen}_rejected.xlsx" if rejected else None,
        dry_run,
    )
    with open(os.path.join(run_dir, f"{screen}_report.txt"), "w", encoding="utf-8") as f:
        f.write(report)

    top_errors = Counter(
        core.categorize_error(r["reason"]) for r in rejected
    ).most_common(10)
    rejected_rows = [(r["excel_row"], r["reason"]) for r in rejected[:12]]

    result_html = render_template_string(
        RESULT,
        total=res["total"], valid=len(valid), rejected=len(rejected),
        run_id=run_id, load_name=load_name, dry_run=dry_run,
        top_errors=top_errors, warnings=res["warnings"], rejected_rows=rejected_rows,
    )
    return render_template_string(PAGE, screens=core.available_screens(),
                                  result=result_html, error=None)


@app.route("/download/<run_id>/<kind>")
def download(run_id, kind):
    if not _RUN_ID_RE.match(run_id):
        abort(404)
    run_dir = os.path.join(WEB_OUTPUT, run_id)
    if not os.path.isdir(run_dir):
        abort(404)
    # מאתרים את הקובץ המבוקש לפי הסוג
    prefix = {"load": "_load.", "rejected": "_rejected.xlsx", "report": "_report.txt"}.get(kind)
    if not prefix:
        abort(404)
    for fname in os.listdir(run_dir):
        if prefix in fname or fname.endswith(prefix):
            return send_from_directory(run_dir, fname, as_attachment=True)
    abort(404)


def _error(msg):
    return render_template_string(PAGE, screens=core.available_screens(),
                                  result=None, error=msg)


if __name__ == "__main__":
    os.makedirs(WEB_OUTPUT, exist_ok=True)
    print("=" * 56)
    print("  ממשק הכנת קבצי טעינה לפריוריטי פועל")
    print("  פתח בדפדפן:  http://127.0.0.1:5000")
    print("  לעצירה: Ctrl+C")
    print("=" * 56)
    app.run(host="127.0.0.1", port=5000, debug=False)
