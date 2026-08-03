# -*- coding: utf-8 -*-
"""
webapp.py — ממשק וובי מקומי להכנת קבצי טעינה לפריוריטי

מעלים קובץ אקסל, בוחרים מסך יעד, ומקבלים טבלת טעינה אינטראקטיבית:
תאים שגויים נצבעים באדום, מתקנים במקום, מוחקים שורות, ומפיקים קובץ טעינה.
תומך גם בקבצים "קשים": שורת כותרת שאינה ראשונה, וקבצים גדולים (עשרות אלפי
שורות) — שבהם מוצגות לתיקון רק השורות השגויות, והתקינות נשמרות בשרת.

הפעלה:  python webapp.py   ואז בדפדפן:  http://127.0.0.1:5000
"""

import base64
import hmac
import io
import os
import re
import time
import uuid

import pandas as pd
from flask import (
    Flask, request, jsonify, render_template_string, send_from_directory, abort,
    session, redirect,
)

import main as core
import journal as jrn
import boi_rates as boi
import db

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 80 * 1024 * 1024  # מגבלת העלאה: 80MB
# מפתח לחתימת ה-cookie של ההתחברות (session). מומלץ להגדיר SECRET_KEY בסביבה
# (ב-Vercel/Render). ה-session נשמר בצד הלקוח כ-cookie חתום — עובד גם ב-serverless.
app.secret_key = os.environ.get("SECRET_KEY") or os.environ.get("APP_SECRET") \
    or "priority-file-loader-dev-secret-change-in-production"

# מסך התחברות: מופעל רק אם הוגדרה סיסמה במשתנה הסביבה APP_PASSWORD.
# ללא APP_PASSWORD — האפליקציה פתוחה (מתאים להרצה מקומית). עם APP_PASSWORD —
# כל העמודים דורשים התחברות. שם המשתמש: APP_USERNAME (ברירת מחדל admin).
AUTH_USER = os.environ.get("APP_USERNAME", "admin")
AUTH_PASS = os.environ.get("APP_PASSWORD")
# נתיבי JSON (נקראים ב-fetch) — עליהם נחזיר 401 במקום הפניה לעמוד התחברות
_AUTH_JSON_PREFIXES = ("/grid/", "/journal/", "/rates/fetch")
_AUTH_OPEN_ENDPOINTS = {"login", "logout", "static"}


@app.before_request
def _require_login():
    if not AUTH_PASS or session.get("auth"):
        return None
    if request.endpoint in _AUTH_OPEN_ENDPOINTS:
        return None
    if request.path.startswith(_AUTH_JSON_PREFIXES):
        return jsonify(error="ההתחברות פגה — רענן את העמוד והתחבר מחדש."), 401
    return redirect("/login?next=" + request.path)


def _auth_on():
    return bool(AUTH_PASS)

WEB_OUTPUT = os.path.join(core.OUTPUT_DIR, "web")
os.makedirs(WEB_OUTPUT, exist_ok=True)   # נדרש גם בהרצת production (gunicorn) שלא עוברת דרך __main__
_RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")

# בקבצים עד גודל זה — כל השורות ניתנות לעריכה בטבלה.
# מעל זה — מוצגות רק השורות השגויות (התקינות נשמרות בשרת) כדי לא להעמיס על הדפדפן.
FULL_GRID_LIMIT = 1500
# תקרת שורות שגויות שנשלחות לדפדפן בבת אחת (השאר נכנסות ישירות ל-rejected).
DISPLAY_CAP = 8000

# מאגר ריצות בזיכרון (כלי מקומי, משתמש יחיד): run_id -> נתוני הריצה
RUNS = {}
_RUNS_MAX = 40

ASSETS_DIR = os.path.join(core.HERE, "assets")

# לוגו ברירת-מחדל (ינשוף מעוגלים בכחול המותג). כדי להשתמש בלוגו האמיתי — פשוט
# שמור קובץ בשם assets/logo.png (או .svg/.jpg) והוא יוצג במקום ברירת המחדל.
_OWL_SVG = (
    '<svg viewBox="0 0 120 120" width="42" height="42" aria-hidden="true" style="flex:none">'
    '<g fill="#1e50c8">'
    '<circle cx="33" cy="16" r="7"/><circle cx="87" cy="16" r="7"/><circle cx="60" cy="30" r="6"/>'
    '<circle cx="41" cy="52" r="7"/><circle cx="79" cy="52" r="7"/>'
    '<circle cx="42" cy="86" r="7"/><circle cx="60" cy="86" r="7"/><circle cx="78" cy="86" r="7"/>'
    '<circle cx="51" cy="102" r="7"/><circle cx="69" cy="102" r="7"/><circle cx="60" cy="115" r="6"/>'
    "</g>"
    '<g fill="none" stroke="#1e50c8" stroke-width="8">'
    '<circle cx="41" cy="52" r="19"/><circle cx="79" cy="52" r="19"/>'
    "</g></svg>"
)


def _logo_file_markup():
    """אם קיים קובץ לוגו ב-assets/ — מחזיר <img> מוטמע (data URI). אחרת None."""
    mimes = {"svg": "image/svg+xml", "png": "image/png", "jpg": "image/jpeg",
             "jpeg": "image/jpeg", "webp": "image/webp"}
    for ext, mime in mimes.items():
        p = os.path.join(ASSETS_DIR, f"logo.{ext}")
        if os.path.exists(p):
            with open(p, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            return f'<img src="data:{mime};base64,{b64}" alt="לוגו" class="logo-img">'
    return None


def brand_html():
    """רצועת המיתוג: הלוגו (קובץ אם קיים, אחרת ינשוף ברירת מחדל) + שם החברה."""
    logo = _logo_file_markup()
    if logo:
        return f'<div class="brand">{logo}</div>'
    return (
        '<div class="brand">' + _OWL_SVG +
        '<div class="brand-tx"><span class="brand-name">יזמקו גורו</span>'
        '<span class="brand-sub">מערכות מידע</span></div></div>'
    )


# סקריפט קצר ל-<head> שמחיל נושא שמור (בהיר/כהה) לפני הרינדור — מונע הבהוב
THEME_HEAD = (
    "<script>(function(){try{var t=localStorage.getItem('fl-theme');"
    "if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}})();</script>"
)


def _prune_runs():
    if len(RUNS) > _RUNS_MAX:  # ניקוי ריצות ישנות
        for old in sorted(RUNS, key=lambda k: RUNS[k]["created"])[:len(RUNS) - _RUNS_MAX]:
            RUNS.pop(old, None)


# ---------------------------------------------------------------------------
# עוזרים
# ---------------------------------------------------------------------------
def _columns_meta(mapping):
    return [{
        "target": c["target"], "source": c.get("source"),
        "title": c.get("title") or "",     # שם השדה בעברית (אם הוגדר) — לתצוגה
        "required": bool(c.get("required")),
        # ערך קבוע/אוטומטי = לא לעריכה; עמודה ידנית (manual) כן ניתנת לעריכה
        "constant": c.get("source") is None and not c.get("manual"),
        "type": c.get("type", "text"),
    } for c in core.all_columns(mapping)]


def _first_reason(cells):
    return next((c["error"] for c in cells if c["error"]), "")


def _sample_warnings(mapping, valid_records, limit=40):
    w = core.check_encoding(valid_records, core.all_columns(mapping),
                            mapping.get("encoding", "windows-1255"))
    return w[:limit], len(w)


def _write_records(run_dir, fname, records, mp):
    """כותב קובץ טעינה מרשומות לפי מיפוי נתון."""
    content = core.build_load_content(records, mp)
    with open(os.path.join(run_dir, fname), "wb") as f:
        f.write(core.load_content_bytes(content, mp))


def _store_snapshot(load_id, mapping, screen, data, run):
    """שומר תמונת-מצב של הטבלה (כל השורות + ערכים) לפתיחה מחדש מההיסטוריה."""
    if not load_id:
        return
    import json
    targets = [c["target"] for c in core.all_columns(mapping)]
    rows = [dict(r) for r in (data.get("rows") or [])]
    excel = list(data.get("excel_rows") or [])
    for rec in run.get("valid", []):                 # שורות תקינות שהוסתרו (קובץ גדול)
        rows.append(dict(zip(targets, rec.get("values", []))))
        excel.append(rec.get("excel_row"))
    for excel_row, values, _reason in run.get("overflow", []):   # שורות שגויות שהוסתרו
        rows.append(dict(values))
        excel.append(excel_row)
    blob = json.dumps({"screen": screen, "rows": rows, "excel_rows": excel,
                       "source_name": run.get("source_name", "")},
                      ensure_ascii=False).encode("utf-8")
    db.add_file(load_id, "__snapshot__.json", "טבלה", "snapshot", blob)


def _store_run_files(load_id, run_dir, files, screen, has_rejected):
    """שומר את קובצי הפלט שנוצרו (טעינה/פסולות/דוח) במסד הנתונים, לאחזור עתידי."""
    if not load_id:
        return
    items = [(f["name"], f.get("label", "קובץ טעינה"), "load") for f in files]
    if has_rejected:
        items.append((f"{screen}_rejected.xlsx", "שורות פסולות", "rejected"))
    items.append((f"{screen}_report.txt", "דוח", "report"))
    for name, label, kind in items:
        path = os.path.join(run_dir, name)
        try:
            with open(path, "rb") as fh:
                db.add_file(load_id, name, label, kind, fh.read())
        except OSError:
            continue


def _rejected_df(mapping, items):
    """items: רשימת (excel_row, {target:value}, reason)."""
    targets = [c["target"] for c in core.all_columns(mapping)]
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
<script>(function(){try{var t=localStorage.getItem('fl-theme');if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}})();</script>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Assistant:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
 :root{
  --bg:#eef2f9;--surface:#ffffff;--surface-2:#f7f9fc;--border:#e5eaf2;
  --text:#0f172a;--muted:#64748b;
  --brand:#4f46e5;--brand-2:#6366f1;--brand-700:#4338ca;
  --green:#059669;--red:#dc2626;--radius:18px;
  --shadow:0 1px 2px rgba(16,24,40,.05),0 8px 24px rgba(16,24,40,.07);
  --shadow-lg:0 20px 50px rgba(37,40,90,.16);
 }
 @media (prefers-color-scheme:dark){:root:not([data-theme]){
  --bg:#0b1120;--surface:#111a2e;--surface-2:#0f1728;--border:#233047;
  --text:#e8edf6;--muted:#93a1b8;--brand:#818cf8;--brand-2:#a5b4fc;--brand-700:#6366f1;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 30px rgba(0,0,0,.4);--shadow-lg:0 24px 60px rgba(0,0,0,.55);
 }}
 :root[data-theme="dark"]{
  --bg:#0b1120;--surface:#111a2e;--surface-2:#0f1728;--border:#233047;
  --text:#e8edf6;--muted:#93a1b8;--brand:#818cf8;--brand-2:#a5b4fc;--brand-700:#6366f1;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 30px rgba(0,0,0,.4);--shadow-lg:0 24px 60px rgba(0,0,0,.55);
 }
 .brand{display:flex;align-items:center;gap:11px}
 .brand .logo-img{height:46px;width:auto}
 .brand-tx{display:flex;flex-direction:column;line-height:1.05}
 .brand-name{font-weight:800;font-size:21px;color:var(--text);letter-spacing:-.01em}
 .brand-sub{font-weight:600;font-size:12.5px;color:#1e50c8}
 .topbar{display:flex;align-items:center;justify-content:space-between;max-width:720px;margin:0 auto 4px;padding:0 2px}
 .themebtn{background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:10px;
  padding:8px 12px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;width:auto;margin:0;box-shadow:none}
 .themebtn:hover{transform:none;background:var(--surface-2);box-shadow:none}
 *{box-sizing:border-box}
 body{margin:0;min-height:100vh;color:var(--text);line-height:1.6;
  font-family:"Assistant",-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,Arial,sans-serif;
  background:
   radial-gradient(1100px 500px at 100% -10%,rgba(99,102,241,.18),transparent 60%),
   radial-gradient(900px 500px at -10% 0%,rgba(16,185,129,.12),transparent 55%),
   var(--bg);}
 .wrap{max-width:720px;margin:0 auto;padding:56px 20px 60px}
 .hero{text-align:center;margin-bottom:26px}
 .logo{width:60px;height:60px;border-radius:18px;margin:0 auto 16px;display:grid;place-items:center;
  font-size:30px;color:#fff;background:linear-gradient(140deg,var(--brand-2),var(--brand));
  box-shadow:0 10px 24px rgba(79,70,229,.4)}
 h1{font-size:28px;font-weight:800;margin:0 0 6px;letter-spacing:-.02em}
 .hero p{color:var(--muted);margin:0;font-size:16px}
 .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  padding:26px;box-shadow:var(--shadow)}
 label{display:block;font-weight:600;margin:0 0 7px;font-size:14px}
 select,input[type=text],input[type=number]{width:100%;padding:11px 13px;border:1.5px solid var(--border);
  border-radius:12px;font-size:15px;font-family:inherit;background:var(--surface-2);color:var(--text);transition:.15s}
 select:focus,input:focus{outline:none;border-color:var(--brand);box-shadow:0 0 0 4px rgba(99,102,241,.15);background:var(--surface)}
 .row{display:flex;gap:14px;flex-wrap:wrap}.row>div{flex:1;min-width:180px;margin-bottom:18px}
 .drop{border:2px dashed var(--border);border-radius:14px;padding:34px 20px;text-align:center;cursor:pointer;
  background:var(--surface-2);transition:.18s;margin-bottom:6px}
 .drop:hover{border-color:var(--brand-2)}
 .drop.over{border-color:var(--brand);background:rgba(99,102,241,.08);transform:scale(1.01)}
 .drop .ico{font-size:30px;display:block;margin-bottom:8px}
 .drop b{color:var(--brand)}.drop small{display:block;color:var(--muted);margin-top:6px}
 .fname{margin-top:12px;font-weight:700;color:var(--green)}
 button{width:100%;background:linear-gradient(140deg,var(--brand-2),var(--brand));color:#fff;border:0;
  border-radius:12px;padding:14px;font-size:16px;font-weight:700;cursor:pointer;margin-top:14px;
  box-shadow:0 8px 20px rgba(79,70,229,.32);transition:.15s;font-family:inherit}
 button:hover{transform:translateY(-1px);box-shadow:0 12px 26px rgba(79,70,229,.42)}
 button:active{transform:translateY(0)}
 .muted{color:var(--muted);font-size:13.5px;text-align:center;margin-top:18px}
 .err{background:rgba(220,38,38,.08);border:1px solid rgba(220,38,38,.3);color:#dc2626;border-radius:12px;padding:16px 18px;white-space:pre-wrap}
 code{background:var(--surface-2);border:1px solid var(--border);padding:2px 7px;border-radius:6px;font-size:13px}
 a.back{color:var(--brand);text-decoration:none;font-weight:700}
</style></head><body><div class="wrap">
 <div class="topbar">{{ brand|safe }}
  <div style="display:flex;gap:8px;align-items:center">
   <a class="themebtn" style="text-decoration:none" href="/rates">💱 שערי בנק ישראל</a>
   <a class="themebtn" style="text-decoration:none" href="/history">📜 היסטוריה</a>
   {% if auth_on %}<a class="themebtn" style="text-decoration:none" href="/logout">🚪 יציאה</a>{% endif %}
   <button id="themebtn" class="themebtn" onclick="toggleTheme()">🌙 מצב כהה</button></div></div>
 <div class="hero">
  <div class="logo">📥</div>
  <h1>הכנת קובץ טעינה ל-Priority ERP</h1>
  <p>העלה קובץ אקסל, בחר מסך יעד, ותקבל טבלת טעינה חכמה לפני הפקת הקובץ.</p>
 </div>
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
   <label>קובץ קלט</label>
   <div class="drop" id="drop"><span class="ico">📄</span><b>גרור לכאן קובץ</b> או לחץ לבחירה<small>xlsx · txt · dat · csv</small>
    <input type="file" id="file" name="file" accept=".xlsx,.xls,.txt,.dat,.csv,.tsv" hidden required>
    <div class="fname" id="fname"></div></div>
   <button type="submit">טען לטבלה ←</button>{% endif %}
  </form>
  <p class="muted">🔒 הכל רץ מקומית על המחשב שלך — הקובץ לא נשלח לשום שרת חיצוני.<br>
   הכלי מזהה אוטומטית את שורת הכותרת גם כשהיא לא בשורה הראשונה.</p>
 {% endif %}
</div><script>
 const drop=document.getElementById('drop'),file=document.getElementById('file'),fname=document.getElementById('fname');
 if(drop){drop.addEventListener('click',()=>file.click());
  file.addEventListener('change',()=>{if(file.files[0])fname.textContent='📄 '+file.files[0].name;});
  ['dragover','dragenter'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add('over');}));
  ['dragleave','drop'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove('over');}));
  drop.addEventListener('drop',ev=>{file.files=ev.dataTransfer.files;if(file.files[0])fname.textContent='📄 '+file.files[0].name;});}
 function toggleTheme(){var r=document.documentElement,cur=r.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
  var nx=cur==='dark'?'light':'dark';r.setAttribute('data-theme',nx);try{localStorage.setItem('fl-theme',nx);}catch(e){}updateThemeBtn();}
 function updateThemeBtn(){var b=document.getElementById('themebtn');if(!b)return;
  var cur=document.documentElement.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
  b.textContent=cur==='dark'?'☀️ מצב בהיר':'🌙 מצב כהה';}
 updateThemeBtn();
</script></body></html>
"""


# ---------------------------------------------------------------------------
# עמוד טבלת הטעינה
# ---------------------------------------------------------------------------
GRID = """
<!doctype html><html lang="he" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>טבלת טעינה — {{ screen }}</title>
<script>(function(){try{var t=localStorage.getItem('fl-theme');if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}})();</script>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Assistant:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
 :root{
  --bg:#eef2f9;--surface:#ffffff;--surface-2:#f7f9fc;--border:#e5eaf2;--text:#0f172a;--muted:#64748b;
  --brand:#4f46e5;--brand-2:#6366f1;--red:#dc2626;
  --bad-bg:#fef2f2;--bad-fg:#dc2626;--warn-bg:#fffbeb;--warn-fg:#b45309;
  --ok-bg:#dcfce7;--ok-fg:#166534;--ign-bg:#e0e7ff;--ign-fg:#4338ca;--tot-bg:#eef2f7;--tot-fg:#334155;
  --shadow:0 1px 2px rgba(16,24,40,.05),0 10px 30px rgba(16,24,40,.07);
 }
 @media (prefers-color-scheme:dark){:root:not([data-theme]){
  --bg:#0b1120;--surface:#111a2e;--surface-2:#0f1728;--border:#233047;--text:#e8edf6;--muted:#93a1b8;
  --brand:#818cf8;--brand-2:#a5b4fc;
  --bad-bg:rgba(220,38,38,.15);--bad-fg:#f87171;--warn-bg:rgba(217,119,6,.16);--warn-fg:#fbbf24;
  --ok-bg:rgba(5,150,105,.18);--ok-fg:#34d399;--ign-bg:rgba(99,102,241,.22);--ign-fg:#a5b4fc;
  --tot-bg:rgba(148,163,184,.16);--tot-fg:#cbd5e1;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 12px 34px rgba(0,0,0,.45);
 }}
 :root[data-theme="dark"]{
  --bg:#0b1120;--surface:#111a2e;--surface-2:#0f1728;--border:#233047;--text:#e8edf6;--muted:#93a1b8;
  --brand:#818cf8;--brand-2:#a5b4fc;
  --bad-bg:rgba(220,38,38,.15);--bad-fg:#f87171;--warn-bg:rgba(217,119,6,.16);--warn-fg:#fbbf24;
  --ok-bg:rgba(5,150,105,.18);--ok-fg:#34d399;--ign-bg:rgba(99,102,241,.22);--ign-fg:#a5b4fc;
  --tot-bg:rgba(148,163,184,.16);--tot-fg:#cbd5e1;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 12px 34px rgba(0,0,0,.45);
 }
 .brand{display:flex;align-items:center;gap:10px}
 .brand .logo-img{height:40px;width:auto}
 .brand-tx{display:flex;flex-direction:column;line-height:1.03}
 .brand-name{font-weight:800;font-size:18px;color:var(--text);letter-spacing:-.01em}
 .brand-sub{font-weight:600;font-size:11.5px;color:#1e50c8}
 .apphead{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:6px}
 .apphead .ttl h1{margin:0}.apphead .ttl .sub{margin:0}
 .themebtn{background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:10px;
  padding:8px 12px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit}
 *{box-sizing:border-box}
 body{margin:0;color:var(--text);font-family:"Assistant",-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,Arial,sans-serif;
  background:radial-gradient(1000px 420px at 100% -8%,rgba(99,102,241,.14),transparent 60%),var(--bg)}
 .wrap{max-width:1460px;margin:0 auto;padding:22px 18px 90px}
 h1{font-size:23px;font-weight:800;margin:0 0 3px;letter-spacing:-.01em}
 .sub{color:var(--muted);font-size:14px;margin:0 0 16px}
 .bar{display:flex;gap:9px;align-items:center;flex-wrap:wrap;padding:12px 14px;margin-bottom:14px;
  background:var(--surface);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow)}
 .pill{border-radius:999px;padding:6px 14px;font-weight:700;font-size:13.5px}
 .pill.tot{background:var(--tot-bg);color:var(--tot-fg)}.pill.ok{background:var(--ok-bg);color:var(--ok-fg)}
 .pill.bad{background:var(--bad-bg);color:var(--bad-fg)}.pill.warn{background:var(--warn-bg);color:var(--warn-fg)}
 .pill.ign{background:var(--ign-bg);color:var(--ign-fg)}
 button{border:0;border-radius:11px;padding:9px 15px;font-size:14px;font-weight:700;cursor:pointer;font-family:inherit;transition:.15s}
 .b-check{background:var(--surface-2);color:var(--text);border:1px solid var(--border)}.b-check:hover{background:var(--border)}
 .b-gen{background:linear-gradient(140deg,#10b981,#059669);color:#fff;box-shadow:0 6px 16px rgba(5,150,105,.32)}
 .b-gen:hover{transform:translateY(-1px);box-shadow:0 10px 22px rgba(5,150,105,.42)}
 .b-save{background:linear-gradient(140deg,var(--brand-2),var(--brand));color:#fff;box-shadow:0 6px 16px rgba(79,70,229,.32)}
 .b-save:hover{transform:translateY(-1px);box-shadow:0 10px 22px rgba(79,70,229,.42)}
 .spacer{flex:1}a.back{color:var(--brand);text-decoration:none;font-weight:700;font-size:14px}
 .chk{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--muted);cursor:pointer}.chk input{width:16px;height:16px;accent-color:var(--brand)}
 .banner{background:rgba(99,102,241,.08);border:1px solid rgba(99,102,241,.25);color:var(--brand);border-radius:12px;padding:11px 15px;margin:8px 0;font-size:14px}
 .tablewrap{overflow:auto;max-height:calc(100vh - 230px);border:1px solid var(--border);border-radius:16px;background:var(--surface);box-shadow:var(--shadow)}
 /* פס-גלילה אופקי עליון — לזוז בין העמודות בלי לרדת לתחתית הטבלה */
 .topscroll{overflow-x:auto;overflow-y:hidden;height:15px;margin-bottom:4px;border:1px solid var(--border);
  border-radius:8px;background:var(--surface-2)}
 .topscroll>div{height:1px}
 table{border-collapse:separate;border-spacing:0;width:100%;font-size:14px}
 th,td{border-bottom:1px solid var(--border);border-left:1px solid var(--border);padding:0;text-align:right;white-space:nowrap}
 th{background:var(--surface-2);padding:10px 12px;position:sticky;top:0;z-index:2}
 th .tgt{font-weight:700}th .src{display:block;font-weight:400;color:var(--muted);font-size:11.5px;direction:ltr}
 th .reqdot{color:var(--bad-fg);font-weight:800}
 th.col{cursor:grab;user-select:none;transition:.15s}th.col:active{cursor:grabbing}
 th.col .grip{color:var(--muted);opacity:.5;font-size:12px;margin-left:5px}
 .rez{position:absolute;left:0;top:0;height:100%;width:9px;cursor:col-resize;z-index:4}
 .rez:hover,.rez.active{background:linear-gradient(to left,var(--brand),transparent)}
 th.col.dragover{background:rgba(99,102,241,.14);box-shadow:inset 0 0 0 2px var(--brand)}
 th.col.dragging{opacity:.4}
 th.rownum,td.rownum{background:var(--surface-2);color:var(--muted);text-align:center;font-size:12px;min-width:44px;padding:6px}
 th.act,td.act{text-align:center;min-width:66px;padding:2px}
 tbody tr:hover td:not(.bad):not(.warn):not(.ign-cell){background:rgba(99,102,241,.045)}
 td input{border:0;background:transparent;width:100%;min-width:110px;padding:9px 11px;font:inherit;color:inherit;outline:none;border-radius:6px}
 td.bad{background:var(--bad-bg);position:relative}td.bad input{color:var(--bad-fg);font-weight:600}
 td.bad::after{content:"!";position:absolute;top:2px;left:5px;color:var(--red);font-weight:800;font-size:11px}
 td.warn{background:var(--warn-bg);position:relative}td.warn input{color:var(--warn-fg);font-weight:600}
 td.warn::after{content:"⚠";position:absolute;top:1px;left:3px;font-size:10px}
 td input:focus{background:var(--surface);box-shadow:inset 0 0 0 2px var(--brand)}
 td.const input{background:var(--surface-2);color:var(--muted)}
 tbody td{position:relative}
 .filldown{position:absolute;left:3px;top:50%;transform:translateY(-50%);cursor:pointer;font-size:12px;font-weight:800;
  background:var(--brand);color:#fff;border-radius:5px;padding:1px 6px;line-height:16px;opacity:0;transition:.1s;z-index:3;user-select:none}
 tbody td:hover .filldown{opacity:.85}.filldown:hover{opacity:1}
 tr.rowbad td.rownum{background:var(--bad-bg);color:var(--bad-fg);font-weight:700}
 .del,.ign{border-radius:8px;padding:5px 8px;font-size:13px;cursor:pointer;font-weight:700;transition:.12s;line-height:1;display:inline-block}
 .del{background:var(--bad-bg);color:var(--bad-fg)}.del:hover{filter:brightness(.95)}
 .ign{background:var(--ign-bg);color:var(--ign-fg);margin-right:4px}.ign:hover{filter:brightness(.96)}
 tr.rowign td.rownum{background:var(--ign-bg);color:var(--ign-fg);font-weight:700}
 tr.rowign td input{color:var(--muted)}
 td.ign-cell{background:var(--ign-bg)}
 .legend{display:flex;gap:14px;color:var(--muted);font-size:12.5px;margin:12px 4px;flex-wrap:wrap;align-items:center}
 .legend i{display:inline-block;width:12px;height:12px;border-radius:4px;vertical-align:middle;margin-left:5px;border:1px solid var(--border)}
 .legend i.sw-bad{background:var(--bad-bg)}.legend i.sw-warn{background:var(--warn-bg)}
 .legend i.sw-const{background:var(--surface-2)}.legend i.sw-ign{background:var(--ign-bg)}
 .msg{border-radius:12px;padding:11px 15px;margin:10px 0;font-weight:600}
 .msg.warnbox{background:var(--warn-bg);color:var(--warn-fg);border:1px solid rgba(217,119,6,.3);font-weight:500}
 .toast{position:fixed;bottom:26px;left:50%;transform:translate(-50%,16px);background:var(--surface);color:var(--text);
  border:1px solid var(--border);border-left:3px solid var(--muted);border-radius:12px;padding:12px 20px;font-weight:600;font-size:14px;
  box-shadow:0 16px 40px rgba(16,24,40,.18);opacity:0;pointer-events:none;transition:opacity .25s ease,transform .25s ease;z-index:60;max-width:90vw}
 .toast.show{opacity:1;transform:translate(-50%,0)}
 .toast.ok{border-left-color:#16a34a}.toast.err{border-left-color:var(--red)}
 .pager{display:flex;gap:10px;align-items:center;justify-content:center;margin:16px 0;font-size:14px;color:var(--muted)}
 .pager button{background:var(--surface);color:var(--text);border:1px solid var(--border)}.pager button:disabled{opacity:.4;cursor:default}
 .dl{display:inline-block;color:#fff;text-decoration:none;border-radius:11px;padding:11px 20px;font-weight:700;margin:6px 8px 6px 0;box-shadow:var(--shadow);transition:.15s;background:linear-gradient(140deg,#10b981,#059669)}
 .dl:hover{transform:translateY(-1px)}
 .dl.rej{background:linear-gradient(140deg,#f43f5e,#dc2626)}.dl.rep{background:linear-gradient(140deg,#64748b,#475569)}
 .hint{color:var(--muted);font-size:13px}
 .mapcard{background:var(--surface);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow);margin:8px 0 4px;padding:2px 16px}
 .mapcard summary{cursor:pointer;font-weight:700;padding:12px 0;list-style:none;display:flex;align-items:center;gap:10px}
 .mapcard summary::-webkit-details-marker{display:none}
 .mapcard summary .chev{color:var(--muted);transition:.15s}.mapcard[open] summary .chev{transform:rotate(90deg)}
 .maphint{color:var(--muted);font-weight:400;font-size:13px}
 .mapbadge{background:var(--bad-bg);color:var(--bad-fg);border-radius:999px;padding:2px 10px;font-size:12px;font-weight:700}
 .mapgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px;padding:6px 0 16px}
 .mapitem{display:flex;flex-direction:column;gap:4px;font-size:13px}
 .mapitem .mapt{font-weight:600;color:var(--muted)}.mapitem.mapreq .mapt{color:var(--bad-fg)}
 .mapitem .mapen{font-weight:400;font-size:11px;color:var(--muted);opacity:.7;direction:ltr}
 .mapitem select{padding:8px 10px;border:1.5px solid var(--border);border-radius:9px;background:var(--surface-2);color:var(--text);font-family:inherit;font-size:13.5px}
 .mapitem.mapreq select{border-color:var(--bad-fg)}
 .mapitem select:focus{outline:none;border-color:var(--brand);box-shadow:0 0 0 3px rgba(99,102,241,.15)}
 .jbar{background:var(--surface);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow);
  padding:12px 16px;margin:8px 0;display:flex;gap:14px;align-items:flex-end;flex-wrap:wrap}
 .jbar .fld{display:flex;flex-direction:column;gap:4px}
 .jbar .fld label{font-size:12px;color:var(--muted);font-weight:600}
 .jbar .fld input{width:110px;padding:8px 10px;border:1.5px solid var(--border);border-radius:9px;background:var(--surface-2);color:var(--text);font-family:inherit;font-size:14px}
 .jbar .fld input:focus{outline:none;border-color:var(--brand)}
 .jbar .jt{font-weight:700;color:var(--brand);align-self:center;margin-inline-end:4px}
 .b-jchk{background:#475569;color:#fff}.b-jbal{background:linear-gradient(140deg,#6366f1,#4f46e5);color:#fff}
 .bar2{margin-top:-6px;padding:10px 14px}.tool-lbl{font-weight:700;color:var(--muted);font-size:14px}
 .bar2 .mini{padding:7px 10px;border:1.5px solid var(--border);border-radius:9px;background:var(--surface-2);color:var(--text);font-family:inherit;font-size:14px}
 .bar2 .mini#bulkval{min-width:200px}
 tr.filterrow th{padding:4px 6px;position:sticky;top:0}
 tr.filterrow input{width:100%;min-width:90px;padding:6px 8px;border:1px solid var(--border);border-radius:7px;background:var(--surface);color:var(--text);font:inherit;font-size:13px}
</style></head><body><div class="wrap">
 <div class="apphead">
  <div class="ttl" style="display:flex;align-items:center;gap:14px">
   <a class="themebtn" style="text-decoration:none" href="/" title="חזרה לדף הבית">🏠 דף הבית</a>
   <h1>טבלת טעינה — {{ screen }}</h1></div>
  <div style="display:flex;align-items:center;gap:14px">{{ brand|safe }}
   <button id="themebtn" class="themebtn" onclick="toggleTheme()">🌙 מצב כהה</button></div>
 </div>
 <div class="bar">
  <span class="pill tot" id="p-tot">סה״כ 0</span>
  <span class="pill ok" id="p-ok">תקינות 0</span>
  <span class="pill bad" id="p-bad">שגויות 0</span>
  <span class="pill warn" id="p-warn">אזהרות 0</span>
  <span class="pill ign" id="p-ign">מיוצאות למרות בעיה 0</span>
  <span class="spacer"></span>
  <button class="b-check" id="toggleview" onclick="toggleView()">🎯 הצג רק שורות בעייתיות</button>
  <button class="b-check" onclick="ignoreAllWarnings()" title="סמן את כל שורות האזהרה כמיוצאות">🚫 התעלם מאזהרות</button>
  <button class="b-check" onclick="revalidate()">🔄 בדוק מחדש</button>
  <button class="b-gen" onclick="generate()">⬇ צור קובץ טעינה</button>
  <button class="b-save" onclick="saveLoad()" title="שמור את הטעינה בהיסטוריה לאחזור עתידי">💾 שמירה בהיסטוריה</button>
  <a class="back" href="/history">📜 היסטוריה</a>
 </div>
 <div class="bar bar2">
  <span class="tool-lbl">🔧 עדכון גורף</span>
  <select id="bulkcol" class="mini"></select>
  <input id="bulkval" class="mini" placeholder="ערך חדש לכל השורות">
  <button class="b-check" onclick="bulkUpdate()">החל על הכל</button>
 </div>
 <div id="banner"></div><div id="mapping"></div><div id="journalbar"></div><div id="toast" class="toast"></div>
 <div class="legend">
  <span><i class="sw-bad"></i>שגוי</span>
  <span><i class="sw-warn"></i>אזהרה</span>
  <span><i class="sw-ign"></i>מיוצא למרות בעיה</span>
  <span><i class="sw-const"></i>ערך קבוע</span>
 </div>
 <div class="topscroll" id="topscroll"><div id="topscroll-inner"></div></div>
 <div class="tablewrap"><table id="grid"></table></div>
 <div class="pager" id="pager"></div>
 <p class="hint" id="dlarea"></p>
<script>
const GRID = {{ grid|tojson }};
const PAGE_SIZE = 100;
let page = 0;
let colOrder = GRID.columns.map((_, i) => i);   // סדר תצוגה/ייצוא של העמודות
let colWidths = {};                             // רוחב מותאם לעמודה (ci -> px)
let colFilter = {};                             // סינון לכל עמודה (ci -> טקסט)
let onlyProblems = false;                        // הצגת שורות בעייתיות בלבד (toggle)
const $ = id => document.getElementById(id);

// עדכון גורף — קובע ערך זהה לכל השורות בעמודה נבחרת
function fillBulkSelect(){
  const sel=$('bulkcol'); if(!sel) return;
  const cur=sel.value;
  sel.innerHTML=GRID.columns.map((c,ci)=>c.constant?'':'<option value="'+ci+'">'+esc(c.target)+'</option>').join('');
  if(cur) sel.value=cur;
}
function bulkUpdate(){
  const sel=$('bulkcol'); if(!sel||sel.value==='') return;
  const ci=+sel.value, val=($('bulkval')||{}).value||'';
  GRID.rows.forEach(r=>{ if(r.cells[ci]) r.cells[ci].value=val; });
  render(); flash('ok','עודכנו '+GRID.rows.length+' שורות בעמודה '+GRID.columns[ci].target+'.');
}
function setFilter(ci,v){ if(v) colFilter[ci]=v; else delete colFilter[ci]; page=0; renderBody(); }
function matchesFilters(r){
  for(const ci in colFilter){
    const cell=r.cells[ci];
    if(!cell || String(cell.value||'').toLowerCase().indexOf(colFilter[ci].toLowerCase())<0) return false;
  }
  return true;
}

// --- שינוי רוחב עמודה בגרירה ---
function applyWidth(ci,w){
  document.querySelectorAll('input[data-ci="'+ci+'"]').forEach(i=>i.style.minWidth=w+'px');
  const th=document.querySelector('th[data-ci="'+ci+'"]'); if(th) th.style.minWidth=w+'px';
}
function startResize(e,ci){
  e.preventDefault(); e.stopPropagation();
  const handle=e.currentTarget, th=handle.parentElement;
  th.setAttribute('draggable','false'); handle.classList.add('active');
  const startX=e.clientX, startW=th.offsetWidth;
  document.body.style.userSelect='none'; document.body.style.cursor='col-resize';
  function mv(ev){ const w=Math.max(60,Math.min(760, startW+(startX-ev.clientX)));
    colWidths[ci]=w; applyWidth(ci,w); }
  function up(){ document.removeEventListener('mousemove',mv); document.removeEventListener('mouseup',up);
    th.setAttribute('draggable','true'); handle.classList.remove('active');
    document.body.style.userSelect=''; document.body.style.cursor=''; }
  document.addEventListener('mousemove',mv); document.addEventListener('mouseup',up);
}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

function overall(){
  let good=0,bad=0;
  for(const r of GRID.rows){ if(r.valid || r.ignore) good++; else bad++; }
  return {total:GRID.server_valid+GRID.rows.length+GRID.overflow,
          valid:GRID.server_valid+good, invalid:bad+GRID.overflow};
}
function displayed(){
  const out=[];
  GRID.rows.forEach((r,gi)=>{
    const attention = !r.ignore && (!r.valid || r.cells.some(c=>c.warning));
    if((!onlyProblems || attention) && matchesFilters(r)) out.push([gi,r]);
  });
  return out;
}
// כפתור-toggle: מציג הכל / רק שורות בעייתיות. בקובץ גדול (errors) — טוען קודם את הכל מהשרת.
function toggleView(){
  if(GRID.mode==='errors'){ showAll(); return; }
  onlyProblems=!onlyProblems; page=0; render(); updateToggleBtn();
}
function updateToggleBtn(){
  const b=$('toggleview'); if(!b) return;
  b.textContent = (GRID.mode==='errors' || onlyProblems) ? '📋 הצג את כל השורות' : '🎯 הצג רק שורות בעייתיות';
}
function computeSlice(){
  const disp=displayed();
  const pages=Math.max(1,Math.ceil(disp.length/PAGE_SIZE));
  if(page>=pages) page=pages-1; if(page<0) page=0;
  return {disp,pages,slice:disp.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE)};
}
function buildRows(slice,cols){
  let h='';
  for(const [gi,r] of slice){
    const problem = !r.valid || r.cells.some(c=>c.warning);
    const rowcls = r.ignore ? 'rowign' : (r.valid ? '' : 'rowbad');
    let act='<span class="del" title="מחק שורה" onclick="delRow('+gi+')">🗑</span>';
    if(problem) act+='<span class="ign" title="'+(r.ignore?'בטל התעלמות':'התעלם מהבעיה — ייצא בכל זאת')+
       '" onclick="toggleIgnore('+gi+')">'+(r.ignore?'↩':'🚫')+'</span>';
    h+='<tr class="'+rowcls+'"><td class="act">'+act+'</td><td class="rownum">'+r.excel_row+'</td>';
    for(const ci of colOrder){
      const cell=r.cells[ci], c=cols[ci];
      let cls=c.constant?'const':'';
      if(r.ignore){ if(cell.error||cell.warning) cls+=' ign-cell'; }
      else if(cell.error) cls='bad '+cls;
      else if(cell.warning) cls='warn '+cls;
      const title=cell.error?' title="'+esc(cell.error)+'"':(cell.warning?' title="'+esc(cell.warning)+'"':'');
      const ro=c.constant?' readonly':'';
      const wst=colWidths[ci]?' style="min-width:'+colWidths[ci]+'px"':'';
      const fd=c.constant?'':'<span class="filldown" title="מלא ערך זה לכל השורות בעמודה" onclick="fillDown('+gi+','+ci+')">⤓</span>';
      h+='<td class="'+cls+'"'+title+'><input data-ci="'+ci+'" value="'+esc(cell.value)+'"'+ro+wst+
         ' oninput="upd('+gi+','+ci+',this.value)">'+fd+'</td>';
    }
    h+='</tr>';
  }
  if(!slice.length) h+='<tr><td class="act"></td><td class="rownum">–</td><td colspan="'+cols.length+
     '" style="padding:16px;color:#16a34a;font-weight:600">אין שורות להצגה 🎉</td></tr>';
  return h;
}
function render(){
  const cols=GRID.columns;
  const {disp,pages,slice}=computeSlice();
  let h='<thead><tr><th class="act"></th><th class="rownum">#</th>';
  for(const ci of colOrder){ const c=cols[ci];
    const w=colWidths[ci]?' style="min-width:'+colWidths[ci]+'px"':'';
    h+='<th class="col" draggable="true" data-ci="'+ci+'"'+w+' ondragstart="dragStart(event,'+ci+
       ')" ondragover="dragOver(event)" ondragleave="dragLeave(event)" ondrop="dropCol(event,'+ci+
       ')" ondragend="dragEnd(event)"><span class="rez" title="גרור לשינוי רוחב" onmousedown="startResize(event,'+ci+
       ')"></span><span class="grip">⋮⋮</span><span class="tgt">'+esc(c.title||c.target)+
       (c.required?' <span class="reqdot" title="שדה חובה">•</span>':'')+
       '</span><span class="src">'+(c.title?esc(c.target):(c.constant?'ערך קבוע':esc(c.source||'')))+'</span></th>';
  }
  h+='</tr>';
  h+='<tr class="filterrow"><th class="act"></th><th class="rownum">🔎</th>';   // סינון קבוע לכל עמודה
  for(const ci of colOrder)
    h+='<th><input value="'+esc(colFilter[ci]||'')+'" placeholder="סנן" oninput="setFilter('+ci+',this.value)"></th>';
  h+='</tr></thead><tbody id="gridbody">'+buildRows(slice,cols)+'</tbody>';
  $('grid').innerHTML=h;
  renderPager(disp.length,pages);
  updateCounts();
  try{ syncScroll(); }catch(e){}
}
// עדכון רק גוף הטבלה (בלי לבנות מחדש את שורת הסינון) — כדי לשמור פוקוס בכתיבה
function renderBody(){
  const b=$('gridbody'); if(!b){ render(); return; }
  const {disp,pages,slice}=computeSlice();
  b.innerHTML=buildRows(slice,GRID.columns);
  renderPager(disp.length,pages);
  updateCounts();
}
// גלילה אופקית נגישה: פס עליון מסונכרן + גלילה עם Shift+גלגלת (בנוסף לפס התחתון של הקופסה)
function syncScroll(){
  const wrap=document.querySelector('.tablewrap'), top=$('topscroll'), inner=$('topscroll-inner'), grid=$('grid');
  if(!wrap||!top||!inner||!grid) return;
  requestAnimationFrame(()=>{
    inner.style.width=grid.scrollWidth+'px';
    top.style.display = grid.scrollWidth>wrap.clientWidth ? 'block' : 'none';
  });
  if(wrap.__sync) return;
  wrap.__sync=true; let lock=false;
  top.addEventListener('scroll',()=>{if(lock)return;lock=true;wrap.scrollLeft=top.scrollLeft;lock=false;});
  wrap.addEventListener('scroll',()=>{if(lock)return;lock=true;top.scrollLeft=wrap.scrollLeft;lock=false;});
  wrap.addEventListener('wheel',e=>{
    if(e.shiftKey && wrap.scrollWidth>wrap.clientWidth){ wrap.scrollLeft+=(e.deltaY||e.deltaX); e.preventDefault(); }
  },{passive:false});
  window.addEventListener('resize',()=>{ if(grid) inner.style.width=grid.scrollWidth+'px'; });
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
  const warned=GRID.rows.filter(r=>!r.ignore && r.cells.some(c=>c.warning)).length;
  $('p-warn').textContent='אזהרות '+warned; $('p-warn').style.display = warned? '' : 'none';
  const ign=GRID.rows.filter(r=>r.ignore).length;
  $('p-ign').textContent='מיוצאות למרות בעיה '+ign; $('p-ign').style.display = ign? '' : 'none';
}
function upd(gi,ci,val){ GRID.rows[gi].cells[ci].value=val; }
// מילוי ערך תא לכל שאר השורות של אותה עמודה (כמו גרירה באקסל).
// כשיש סינון פעיל — ממלא רק את השורות המסוננות/המוצגות.
async function fillDown(gi,ci){
  const src=GRID.rows[gi] && GRID.rows[gi].cells[ci];
  if(!src) return;
  const val=src.value; let n=0;
  const visible=new Set(displayed().map(x=>x[0]));   // אינדקסים של השורות המוצגות
  GRID.rows.forEach((r,idx)=>{ if(visible.has(idx) && r.cells[ci] && r.cells[ci].value!==val){ r.cells[ci].value=val; n++; } });
  const nm=GRID.columns[ci].title||GRID.columns[ci].target;
  const filtered = Object.keys(colFilter).length>0 || onlyProblems;
  await revalidate();
  flash('ok','מולא "'+esc(val)+'" ל-'+n+(filtered?' שורות מסוננות':' שורות')+' בעמודה «'+esc(nm)+'».');
}
function delRow(gi){ GRID.rows.splice(gi,1); render(); }
function toggleIgnore(gi){ GRID.rows[gi].ignore=!GRID.rows[gi].ignore; render(); }
function ignoreAllWarnings(){
  let n=0;
  GRID.rows.forEach(r=>{ if(!r.ignore && r.valid && r.cells.some(c=>c.warning)){ r.ignore=true; n++; } });
  render();
  flash(n?'ok':'err', n? (n+' שורות אזהרה סומנו — ייכללו בייצוא ללא התראה.') : 'אין שורות אזהרה להתעלמות.');
}

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

// --- פאנל מיפוי עמודות (Excel -> שדה פריוריטי) ---
function renderMapping(){
  const box=$('mapping'); if(!box||!GRID.excel_columns) return;
  const req=new Set(GRID.unmatched_required||[]);
  const cols=GRID.excel_columns, mapped=GRID.columns.filter(c=>!c.constant);
  const auto=mapped.filter(c=>GRID.assignment[c.target]).length;
  const open = req.size>0 ? ' open' : '';
  let h='<details class="mapcard"'+open+'><summary><span class="chev">▸</span>'+
        '🔗 מיפוי עמודות (Excel → שדה פריוריטי)'+
        (req.size>0?' <span class="mapbadge">'+req.size+' שדות חובה לא מופו</span>':'')+
        '<span class="maphint">'+auto+'/'+mapped.length+' שדות מופו · בחר עמודת מקור לכל שדה</span></summary><div class="mapgrid">';
  for(const c of mapped){
    const cur=GRID.assignment[c.target]||'', bad=req.has(c.target);
    const hint=c.source?(Array.isArray(c.source)?c.source[0]:c.source):'';
    h+='<label class="mapitem'+(bad?' mapreq':'')+'"><span class="mapt">'+esc(c.title||c.target)+
       (c.title?' <span class="mapen">'+esc(c.target)+'</span>':'')+
       ((c.required||bad)?' • חובה':'')+'</span><select data-t="'+esc(c.target)+'" onchange="remap()">'+
       '<option value="">— לא ממופה —</option>';
    for(const ex of cols) h+='<option value="'+esc(ex)+'"'+(ex===cur?' selected':'')+'>'+esc(ex)+'</option>';
    h+='</select></label>';
  }
  box.innerHTML=h+'</div></details>';
}
function collectAssignment(){
  const a={};
  document.querySelectorAll('#mapping select[data-t]').forEach(s=>a[s.getAttribute('data-t')]=s.value);
  return a;
}
async function remap(){
  const res=await post('/grid/remap',{run_id:GRID.run_id, assignment:collectAssignment()});
  if(!res) return;
  const openState=document.querySelector('.mapcard') && document.querySelector('.mapcard').open;
  Object.assign(GRID,res); page=0;
  renderBanner(); renderMapping(); render();
  const d=document.querySelector('.mapcard'); if(d) d.open = openState!==false;
  flash('ok','המיפוי עודכן — הטבלה חושבה מחדש.');
}

// --- מנוע הסבת תנועות יומן ---
function renderJournal(){
  const box=$('journalbar'); if(!box) return;
  if(!GRID.journal){ box.innerHTML=''; return; }
  box.innerHTML=
   '<span class="jt">⚖️ תנועות יומן</span>'+
   '<div class="fld"><label>מטבע ראשי</label><input id="j-primary" value="ILS"></div>'+
   '<div class="fld"><label>מטבע משני</label><input id="j-secondary" value="USD"></div>'+
   '<div class="fld"><label>סף איזון ראשי</label><input id="j-maxp" type="number" step="0.01" value="1"></div>'+
   '<div class="fld"><label>סף איזון משני</label><input id="j-maxs" type="number" step="0.01" value="1"></div>'+
   '<button class="b-jchk" onclick="journalFx()">💱 טיוב מט"ח</button>'+
   '<button class="b-jchk" onclick="journalCheck()">🔍 בדיקת תנועות</button>'+
   '<button class="b-jbal" onclick="journalBalance()">⚖️ איזון תנועות</button>';
}
function journalOpts(){
  return {secondary: ($('j-secondary')||{}).value||'', primary: ($('j-primary')||{}).value||'',
          max_primary: ($('j-maxp')||{}).value||'0', max_secondary: ($('j-maxs')||{}).value||'0'};
}
async function journalFx(){ await journalRun('/journal/fx','טיוב מט"ח'); }
async function journalCheck(){ await journalRun('/journal/check','נבדקו התנועות'); }
async function journalBalance(){ await journalRun('/journal/balance','בוצע איזון תנועות'); }
async function journalRun(url,label){
  const body=collect(); body.opts=journalOpts();
  const res=await post(url,body); if(!res)return;
  GRID.rows=res.rows; render();
  const s=res.summary||{};
  const bad = s.unbalanced||s.date_issues||s.zero_rows;
  flash(bad? 'err':'ok',
    label+': '+ (s.balanced||0)+'/'+(s.transactions||0)+' תנועות מאוזנות'+
    (s.fx_changed? (' · מט"ח: '+s.fx_changed+' שורות'):'')+
    (s.fixed? (' · אוזנו '+s.fixed):'')+
    (s.unbalanced? (' · '+s.unbalanced+' לא מאוזנות'):'')+
    (s.date_issues? (' · '+s.date_issues+' תנועות עם תאריך לא אחיד'):'')+
    (s.zero_rows? (' · '+s.zero_rows+' שורות עם סכום 0 (לא ייטענו)'):'')+
    (bad?' — ראה הערות':''));
}

function renderBanner(){
  let b='';
  (GRID.map_warnings||[]).forEach(w=>{ b+='<div class="msg warnbox">🛈 '+esc(w)+'</div>'; });
  if(GRID.mode==='errors')
    b+='<div class="banner">📁 קובץ גדול: '+GRID.server_valid.toLocaleString()+
       ' שורות תקינות נשמרו בשרת ויכללו בקובץ הטעינה. כאן מוצגות רק '+GRID.rows.length+
       ' השורות שדורשות תיקון'+(GRID.overflow>0?(' (ועוד '+GRID.overflow+' שורות שגויות שלא נכנסות לתצוגה)'):'')+'.</div>';
  if(GRID.total_warn>0)
    b+='<div class="msg warnbox">⚠ '+GRID.total_warn+' שורות עם אזהרות פורמט (טלפון/דוא"ל לא תקין). '+
       'האזהרות אינן פוסלות — השורות ייכללו בקובץ הטעינה, אך מומלץ לבדוק ולתקן.</div>';
  if(GRID.warn_count>0)
    b+='<div class="msg warnbox">⚠ אזהרות קידוד ('+GRID.warn_count+'): תווים שלא ניתנים ל-windows-1255 יוחלפו ב-?. '+
       esc((GRID.warnings||[]).slice(0,2).join(' | '))+(GRID.warn_count>2?' ...':'')+'</div>';
  $('banner').innerHTML=b;
}
function collect(){
  return {screen:GRID.screen, run_id:GRID.run_id,
    rows:GRID.rows.map(r=>{const o={};r.cells.forEach(c=>o[c.target]=c.value);return o;}),
    excel_rows:GRID.rows.map(r=>r.excel_row),
    ignore:GRID.rows.map(r=>!!r.ignore),                 // שורות שסומנו להתעלמות
    order:colOrder.map(ci=>GRID.columns[ci].target)};   // סדר עמודות לייצוא
}
function keepIgnore(newRows){   // שמירת סימוני ההתעלמות אחרי רענון מהשרת
  const old=GRID.rows;
  newRows.forEach((r,i)=>{ if(old[i]) r.ignore=old[i].ignore; });
  return newRows;
}
async function showAll(){
  const res=await post('/grid/all',collect()); if(!res)return;
  GRID.rows=res.rows; GRID.server_valid=0; GRID.overflow=0; GRID.total=res.total;
  GRID.total_warn=res.total_warn; GRID.warnings=res.warnings; GRID.warn_count=res.warn_count;
  GRID.mode='all'; page=0; onlyProblems=false; updateToggleBtn();
  renderBanner(); render();
  flash('ok','נטענו כל '+res.total+' השורות.');
}
async function revalidate(){
  const res=await post('/grid/validate',collect()); if(!res)return;
  GRID.rows=keepIgnore(res.rows); render();
  const o=overall();
  flash(o.invalid===0?'ok':'err', o.invalid===0?'✓ כל השורות תקינות — אפשר לייצר קובץ טעינה.':
        'נותרו '+o.invalid+' שורות עם שגיאות לתיקון.');
}
function showDownloads(res, saved){
  if(res.rows){ GRID.rows=keepIgnore(res.rows); GRID.server_valid=res.server_valid; GRID.overflow=res.overflow; render(); }
  let html='';
  if(res.files && res.files.length){   // מסמך: קובץ אב + מסכי-משנה
    res.files.forEach(f=>{ html+='<a class="dl" href="/download/'+res.run_id+'/f/'+encodeURIComponent(f.name)+'">⬇ '+esc(f.label)+'</a>'; });
    html+='<a class="dl rep" href="/download/'+res.run_id+'/report">⬇ דוח</a>';
  } else if(res.valid>0){
    html+='<a class="dl" href="/download/'+res.run_id+'/load">⬇ הורדת קובץ הטעינה ('+esc(res.load_name)+')</a>';
    html+='<a class="dl rep" href="/download/'+res.run_id+'/report">⬇ דוח</a>'; }
  if(res.invalid>0) html+='<a class="dl rej" href="/download/'+res.run_id+'/rejected">⬇ שורות פסולות ('+res.invalid+')</a>';
  if(saved) html+='<a class="dl" href="/history">📜 צפה בהיסטוריה</a>';
  $('dlarea').innerHTML=html;
}
async function generate(){
  const res=await post('/grid/generate',collect()); if(!res)return;
  showDownloads(res,false);
  flash(res.invalid>0?'err':'ok',
    res.invalid>0?('נוצר קובץ טעינה עם '+res.valid+' שורות תקינות. '+res.invalid+' שורות שגויות לא נכללו.'):
                  ('✓ נוצר קובץ טעינה מלא עם '+res.valid+' שורות. לחץ להורדה.'));
}
async function saveLoad(){
  const res=await post('/grid/save',collect()); if(!res)return;
  showDownloads(res,true);
  if(res.load_id)
    flash('ok','✓ הטעינה נשמרה בהיסטוריה ('+res.valid+' שורות). ראה מסך היסטוריה.');
  else
    flash('err','הטעינה הופקה אך שמירת ההיסטוריה נכשלה — בדוק את חיבור מסד הנתונים במסך ההיסטוריה.');
}
async function post(url,body){
  try{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const j=await r.json(); if(!r.ok||j.error){flash('err','שגיאה: '+(j.error||r.status));return null;} return j;
  }catch(e){flash('err','תקלה בתקשורת עם השרת: '+e);return null;}
}
let ft=null;
function flash(kind,text){const t=$('toast');if(!t)return;
  t.textContent=text;t.className='toast '+(kind==='ok'?'ok':'err')+' show';
  clearTimeout(ft);ft=setTimeout(()=>{t.classList.remove('show');},3000);}

function toggleTheme(){var r=document.documentElement,cur=r.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
  var nx=cur==='dark'?'light':'dark';r.setAttribute('data-theme',nx);try{localStorage.setItem('fl-theme',nx);}catch(e){}updateThemeBtn();}
function updateThemeBtn(){var b=$('themebtn');if(!b)return;
  var cur=document.documentElement.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
  b.textContent=cur==='dark'?'☀️ מצב בהיר':'🌙 מצב כהה';}

updateToggleBtn();
updateThemeBtn(); fillBulkSelect(); renderBanner(); renderMapping(); renderJournal(); render();
</script></body></html>
"""


# ---------------------------------------------------------------------------
# נתיבים
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template_string(UPLOAD, screens=core.available_screens(), error=None,
                                  brand=brand_html(), auth_on=_auth_on())


def _build_grid(screen, mapping, df, overrides, run_id=None, source_name=None):
    """
    ליבת בניית תגובת הטבלה — משותפת ל-/process ול-/grid/remap.
    פותר את המיפוי (עם overrides ידניים), מריץ ולידציה, מפצל קטן/גדול, שומר את
    הריצה (כולל ה-DataFrame הגולמי כדי לאפשר מיפוי מחדש), ומחזיר payload מלא.
    """
    df = core.preprocess_journal_df(df, mapping)   # סינון שורות + איחוד חובה/זכות/סימן (יומן)
    resolved, req_missing, opt_missing = core.resolve_columns(df, core.all_columns(mapping), overrides)
    rows_out = core.evaluate_grid(mapping, core.rows_from_dataframe(df, mapping, resolved))
    key_fields = mapping.get("key_fields") or []
    total = len(rows_out)

    def _has_warn(r):
        return any(c.get("warning") for c in r["cells"])

    invalid_rows = [r for r in rows_out if not r["valid"]]
    valid_rows = [r for r in rows_out if r["valid"]]

    # במסמכים (מסכי-משנה) כל השורות מוצגות — הבנייה של האב/הבן דורשת אותן
    if total <= FULL_GRID_LIMIT or core.subform_defs(mapping):
        displayed, server_valid = rows_out, []
        reserved, overflow_items = set(), []
    else:
        attention = invalid_rows + [r for r in valid_rows if _has_warn(r)]
        displayed = attention[:DISPLAY_CAP]
        shown = {id(r) for r in displayed}
        hidden_valid = [r for r in valid_rows if id(r) not in shown]
        server_valid = core.grid_valid_records(hidden_valid)
        reserved = {core.row_key(r["cells"], key_fields) for r in hidden_valid} if key_fields else set()
        overflow_items = [
            (r["excel_row"], {c["target"]: c["value"] for c in r["cells"]}, _first_reason(r["cells"]))
            for r in invalid_rows if id(r) not in shown
        ]

    prev = RUNS.get(run_id) or {}
    run_id = run_id or uuid.uuid4().hex
    RUNS[run_id] = {
        "screen": screen, "df": df, "overrides": dict(overrides or {}),
        "valid": server_valid, "reserved": reserved, "overflow": overflow_items,
        "source_name": source_name or prev.get("source_name", ""),
        "created": time.time(),
    }
    _prune_runs()

    warnings, warn_count = _sample_warnings(mapping, core.grid_valid_records(valid_rows))
    total_warn = sum(1 for r in rows_out if _has_warn(r))
    assignment = {
        c["target"]: resolved.get(c["target"], "")
        for c in core.all_columns(mapping) if c.get("source") is not None
    }
    return {
        "screen": screen, "run_id": run_id, "interface": mapping.get("interface_name"),
        "mode": "errors" if total > FULL_GRID_LIMIT else "all",
        "columns": _columns_meta(mapping), "key_fields": key_fields,
        "rows": displayed, "server_valid": len(server_valid),
        "overflow": len(overflow_items), "total": total, "total_warn": total_warn,
        "warnings": warnings, "warn_count": warn_count,
        "map_warnings": core.mapping_field_warnings(mapping, screen),
        "excel_columns": list(df.columns), "assignment": assignment,
        "unmatched_required": req_missing, "unmatched_optional": opt_missing,
        "journal": mapping.get("journal"),  # תפקידי עמודות להסבת תנועות יומן
    }


@app.route("/process", methods=["POST"])
def process():
    screen = (request.form.get("screen") or "").strip()
    sheet = (request.form.get("sheet") or "").strip() or None
    header_row = (request.form.get("header_row") or "").strip()
    header_row = int(header_row) if header_row.isdigit() else None
    upload = request.files.get("file")

    if not upload or not upload.filename:
        return _upload_error("לא נבחר קובץ.")
    if not upload.filename.lower().endswith((".xlsx", ".xls", ".txt", ".dat", ".csv", ".tsv")):
        return _upload_error("יש להעלות קובץ בפורמט xlsx / txt / dat / csv.")

    try:
        mapping = core.load_mapping(screen)
        df = core.read_input(
            io.BytesIO(upload.read()), sheet, filename=upload.filename,
            header_row=header_row if header_row is not None else mapping.get("header_row"),
            expected_sources=core._expected_sources(mapping),
        )
        payload = _build_grid(screen, mapping, df, overrides=None,
                              source_name=upload.filename)
    except core.UserError as e:
        return _upload_error(str(e))
    except Exception as e:  # noqa: BLE001
        return _upload_error(f"שגיאה בלתי צפויה בעיבוד הקובץ:\n{e}")

    return render_template_string(GRID, screen=screen, grid=payload, brand=brand_html())


@app.route("/grid/remap", methods=["POST"])
def grid_remap():
    """מיפוי מחדש: המשתמש בחר עמודת אקסל לשדה — מחשבים את הטבלה מחדש."""
    data = request.get_json(silent=True) or {}
    run = RUNS.get(data.get("run_id"))
    if not run or run.get("df") is None:
        return jsonify(error="הריצה פגה מהזיכרון — טען מחדש את הקובץ."), 400
    try:
        mapping = core.load_mapping(run["screen"])
        overrides = data.get("assignment") or {}
        payload = _build_grid(run["screen"], mapping, run["df"], overrides, run_id=data["run_id"])
    except core.UserError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"שגיאה במיפוי מחדש: {e}"), 400
    return jsonify(payload)


@app.route("/grid/all", methods=["POST"])
def grid_all():
    """טוען את *כל* השורות לטבלה (כולל התקינות ששמורות בשרת), עם שמירת העריכות."""
    data = request.get_json(silent=True) or {}
    run = RUNS.get(data.get("run_id"))
    if not run:
        return jsonify(error="הריצה פגה מהזיכרון — טען מחדש את הקובץ."), 400
    try:
        mapping = core.load_mapping(run["screen"])
        targets = [c["target"] for c in core.all_columns(mapping)]

        # שורות מוצגות (עם העריכות של המשתמש) + שורות תקינות שמורות + overflow
        inputs = list(data.get("rows") or [])
        excel = list(data.get("excel_rows") or [])
        for rec in run.get("valid", []):
            vals = rec["values"]
            inputs.append({targets[k]: (vals[k] if k < len(vals) else "") for k in range(len(targets))})
            excel.append(rec.get("excel_row"))
        for excel_row, values, _reason in run.get("overflow", []):
            inputs.append(dict(values))
            excel.append(excel_row)

        order = sorted(range(len(inputs)), key=lambda i: excel[i] if excel[i] is not None else 0)
        inputs = [inputs[i] for i in order]
        excel = [excel[i] for i in order]
        rows_out = core.evaluate_grid(mapping, inputs, excel_rows=excel)
    except core.UserError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"שגיאה בטעינת כל השורות: {e}"), 400

    # מעתה הלקוח מחזיק את כל השורות — מנקים את השמור בשרת כדי לא לספור פעמיים
    run["valid"], run["reserved"], run["overflow"] = [], set(), []
    warnings, warn_count = _sample_warnings(
        mapping, core.grid_valid_records([r for r in rows_out if r["valid"]]))
    return jsonify(
        rows=rows_out, server_valid=0, overflow=0, total=len(rows_out),
        total_warn=sum(1 for r in rows_out if any(c.get("warning") for c in r["cells"])),
        warnings=warnings, warn_count=warn_count,
    )


def _notes_target(mapping):
    """מוצא את עמודת ההערות למיישם (manual + exclude)."""
    for c in mapping["columns"]:
        if c.get("manual") and c.get("exclude"):
            return c["target"]
    return None


def _strip_auto_note(text):
    """מסיר הערת-איזון אוטומטית קודמת (הכל מ-⚠ ואילך), משאיר הערה ידנית."""
    return (str(text or "").split("⚠")[0]).rstrip()


# מילים נרדפות נפוצות לשקל בקבצי תנועות יומן — אינן בטבלת המטבעות, ולכן ממופות ידנית
_ILS_ALIASES = {'ILS', 'NIS', 'שח', 'ש"ח', 'ש”ח', 'שקל', 'שקלים', '₪'}


def _cur_key(value):
    """מפתח השוואת מטבעות עמיד: פותר קוד/תיאור מול טבלת המטבעות, עם מיפוי שקל."""
    v = str(value or "").strip()
    if v == "":
        return ""
    if core._norm_header(v) in {core._norm_header(a) for a in _ILS_ALIASES}:
        return "ILS"
    code = core.lookup_value("currencies", v) or v
    return core._norm_header(code)


def _journal_fx(mapping, rows_dicts, primary, secondary):
    """
    כללי מט"ח לתנועות יומן:
    1) מטח עסקה = מטבע ראשי (ש"ח) -> לא תקין: מחיקת מטבע העסקה והסכום.
    2) מטח עסקה = מטבע משני -> העתקת סכום מטח העסקה לעמודת הסכום המשני.
    מחזיר מספר שורות שהושפעו.
    """
    jc = mapping.get("journal") or {}
    cf, af, asec = jc.get("currency_fx"), jc.get("amount_fx"), jc.get("amount_secondary")
    if not cf:
        return 0
    prim = _cur_key(primary)
    sec = _cur_key(secondary)
    changed = 0
    for row in rows_dicts:
        raw = str(row.get(cf, "") or "").strip()
        if raw == "":
            continue
        n = _cur_key(raw)
        if prim and n == prim:                       # (1) = ראשי -> מחיקה
            row[cf] = ""
            if af:
                row[af] = ""
            changed += 1
        elif sec and n == sec and asec and af:       # (2) = משני -> העתקת הסכום
            if str(row.get(af, "") or "").strip() != "":
                row[asec] = row.get(af, "")
                changed += 1
    return changed


def _journal_process(mapping, rows_dicts, excel_rows, opts, do_balance, do_fx=False):
    """
    מנוע האיזון: (א) איזון אוטומטי אופציונלי, (ב) בדיקת איזון לכל תנועה,
    כתיבת הסבר לעמודת ההערות, וסימון (אזהרה) על שורות תנועה לא-מאוזנת.
    מחזיר (rows_out, summary).
    """
    jc = mapping.get("journal") or {}
    txn, dc = jc.get("txn"), jc.get("dc")
    ap, asec = jc.get("amount_primary"), jc.get("amount_secondary")
    tol_p = tol_s = 0.005
    max_p = jrn.to_number(opts.get("max_primary")) or 0.0
    max_s = jrn.to_number(opts.get("max_secondary")) or 0.0
    use_sec = bool(opts.get("secondary")) and bool(asec)
    notes_t = _notes_target(mapping)

    fx_changed = 0
    if do_fx:
        fx_changed = _journal_fx(mapping, rows_dicts, opts.get("primary"), opts.get("secondary"))

    # סוג תנועה לפי הסכום הראשי: 0 -> הש, אחרת -> מ
    tt_t, tt_zero, tt_non = jc.get("transtype"), jc.get("transtype_zero"), jc.get("transtype_nonzero")
    if tt_t and ap and (tt_zero or tt_non):
        for rd in rows_dicts:
            rd[tt_t] = tt_zero if core._is_zero_amount(rd.get(ap)) else tt_non

    db_t, dr_t = jc.get("date_balance"), jc.get("date_ref")
    zcols = mapping.get("exclude_if_all_zero") or []

    groups = jrn.group_by_txn(rows_dicts, txn) if txn else {}
    fixed = 0
    if do_balance:
        for key, idxs in groups.items():
            if not key:
                continue
            fi, _ = jrn.auto_balance(rows_dicts, idxs, ap, dc, max_p, tol_p)
            if fi is not None:
                fixed += 1
            if use_sec:
                jrn.auto_balance(rows_dicts, idxs, asec, dc, max_s, tol_s)

    notes_by_row = {}        # i -> [הערות אוטומטיות]

    def _note(i, txt):
        notes_by_row.setdefault(i, []).append(txt)

    flagged, unbalanced, date_issues = set(), 0, 0
    for key, idxs in groups.items():
        if not key:
            continue
        # (א) איזון התנועה
        parts = []
        bp = jrn.transaction_balance(rows_dicts, idxs, ap, dc, tol_p)
        if not bp["balanced"]:
            parts.append(f"מטבע ראשי חסר {jrn._fmt(abs(bp['diff']))}")
        if use_sec:
            bs = jrn.transaction_balance(rows_dicts, idxs, asec, dc, tol_s)
            if not bs["balanced"]:
                parts.append(f"מטבע משני חסר {jrn._fmt(abs(bs['diff']))}")
        if parts:
            for i in idxs:
                _note(i, "תנועה לא מאוזנת (" + " · ".join(parts) + ")")
            flagged.update(idxs)
            unbalanced += 1
        # (ב) תאריך מאזן אחד ותאריך אסמכתא אחד לכל התנועה
        for tcol, lbl in ((db_t, "מאזן"), (dr_t, "אסמכתא")):
            if not tcol:
                continue
            vals = {str(rows_dicts[i].get(tcol, "") or "").strip() for i in idxs}
            if len(vals) > 1:
                for i in idxs:
                    _note(i, f"תאריך {lbl} אינו אחיד בתנועה")
                flagged.update(idxs)
                date_issues += 1

    # (ג) שורה שכל הסכומים בה 0 — הערה + לא תיטען (הפסילה מתבצעת ב-evaluate_grid)
    zero_rows = 0
    if zcols:
        for i, rd in enumerate(rows_dicts):
            if all(core._is_zero_amount(rd.get(t)) for t in zcols):
                _note(i, "כל הסכומים 0 — השורה לא תיטען")
                zero_rows += 1

    # כתיבת ההערות: בסיס ידני + הערות אוטומטיות מרועננות (מנקה הערות ישנות)
    if notes_t is not None:
        for i, rd in enumerate(rows_dicts):
            base = _strip_auto_note(rd.get(notes_t, ""))
            auto = notes_by_row.get(i)
            rd[notes_t] = (base + " " if base and auto else base) + \
                          ("⚠ " + " · ".join(auto) if auto else "")

    rows_out = core.evaluate_grid(mapping, rows_dicts, excel_rows=excel_rows)
    for i in flagged:  # צביעה בכתום (שורות עם בעיה שאינה פוסלת, כמו חוסר איזון)
        for c in rows_out[i]["cells"]:
            if c["target"] == ap and not c["error"] and not c["warning"]:
                c["warning"] = "שורה לבדיקה"
    total_txn = sum(1 for k in groups if k)
    return rows_out, {"unbalanced": unbalanced, "balanced": total_txn - unbalanced,
                      "transactions": total_txn, "fixed": fixed, "fx_changed": fx_changed,
                      "date_issues": date_issues, "zero_rows": zero_rows}


def _journal_endpoint(do_balance=False, do_fx=False):
    data = request.get_json(silent=True) or {}
    run = RUNS.get(data.get("run_id"))
    if not run:
        return jsonify(error="הריצה פגה מהזיכרון — טען מחדש את הקובץ."), 400
    try:
        mapping = core.load_mapping(run["screen"])
        if not (mapping.get("journal")):
            return jsonify(error="המסך אינו מסך תנועות יומן."), 400
        rows_dicts = list(data.get("rows") or [])
        rows_out, summary = _journal_process(
            mapping, rows_dicts, data.get("excel_rows"), data.get("opts") or {},
            do_balance, do_fx)
    except core.UserError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"שגיאה בעיבוד תנועות: {e}"), 400
    return jsonify(rows=rows_out, summary=summary)


@app.route("/journal/check", methods=["POST"])
def journal_check():
    return _journal_endpoint(do_balance=False)


@app.route("/journal/balance", methods=["POST"])
def journal_balance():
    return _journal_endpoint(do_balance=True)


@app.route("/journal/fx", methods=["POST"])
def journal_fx():
    return _journal_endpoint(do_fx=True)


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


def _produce_load(save):
    """
    מפיק את קובץ/י הטעינה מטבלת הטעינה. save=False — הפקה להורדה בלבד;
    save=True — בנוסף רושם את הטעינה בהיסטוריה (מסד הנתונים) ושומר את הקבצים
    לאחזור עתידי.
    """
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

    # "התעלם מבעיה" — שורות שסומנו ידנית ייכללו בייצוא למרות שגיאה/אזהרה
    ignore = data.get("ignore") or []
    for i, r in enumerate(rows_out):
        if i < len(ignore) and ignore[i]:
            r["valid"] = True
            r["forced"] = True

    now_valid = [r for r in rows_out if r["valid"]]
    still_invalid = [r for r in rows_out if not r["valid"]]
    valid_records = run["valid"] + core.grid_valid_records(now_valid)

    # סדר עמודות מבוקש (אם המשתמש סידר מחדש בטבלה) — חל על קובץ הטעינה ועל rejected.
    # לא רלוונטי למסמכים (אב/בן) שבהם הסדר קבוע לפי הרמות.
    order = data.get("order")
    export_mapping = mapping
    if order and not mapping.get("leveled") and not core.subform_defs(mapping):
        valid_records, export_mapping = core.reorder_for_export(valid_records, mapping, order)

    run_id = uuid.uuid4().hex
    run_dir = os.path.join(WEB_OUTPUT, run_id)
    os.makedirs(run_dir, exist_ok=True)

    files = []  # קבצי טעינה שנוצרו: [{name, label}]
    load_name = f"{screen}_load.{core.load_file_extension(mapping)}"
    if mapping.get("leveled"):
        # מסמך רב-רמתי — קובץ אחד עם מזהה רמה (1=אב, 2=בן) בעמודה הראשונה.
        # סדר העמודות שהמשתמש קבע בטבלה מיושם בתוך כל רמה בנפרד.
        content = core.build_leveled_content(valid_records, mapping, order=order)
        if content:
            with open(os.path.join(run_dir, load_name), "wb") as f:
                f.write(core.load_content_bytes(content, mapping))
            files.append({"name": load_name, "label": f"קובץ טעינה רב-רמתי · {screen}"})
    elif core.subform_defs(mapping):
        # מסמך: קובץ אב (ייחודי לפי מפתח) + קובץ לכל מסך-משנה (מקושר במפתח)
        parent_records = core.build_parent_records(now_valid, mapping)
        if parent_records:
            _write_records(run_dir, load_name, parent_records, mapping)
            files.append({"name": load_name, "label": f"קובץ אב · {screen}"})
        for sf in core.subform_defs(mapping):
            vm = core.subform_mapping(mapping, sf)
            fn = f"{screen}_{sf['name']}_load.{core.load_file_extension(vm)}"
            if now_valid:
                _write_records(run_dir, fn, core.build_subform_records(now_valid, mapping, sf), vm)
                files.append({"name": fn, "label": f"מסך-משנה · {sf['name']}"})
    elif valid_records:
        _write_records(run_dir, load_name, valid_records, export_mapping)
        files.append({"name": load_name, "label": "קובץ טעינה"})

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

    load_id = None
    if save:   # רישום בהיסטוריה (רשומה אחת לכל קובץ — עדכון אם כבר קיים) + שמירת קבצים
        load_id = db.upsert_load({
            "screen": screen, "source": run.get("source_name", ""),
            "total": len(valid_records) + len(rejected_items),
            "valid": len(valid_records), "invalid": len(rejected_items),
            "warnings": warn_count, "via": "web", "run_id": run_id,
            "has_rejected": bool(rejected_items),
            "user": (session.get("user") if _auth_on() else "") or "",
        })
        _store_run_files(load_id, run_dir, files, screen, bool(rejected_items))
        _store_snapshot(load_id, mapping, screen, data, run)

    return jsonify(
        run_id=run_id, load_name=load_name, files=files,
        valid=len(valid_records), invalid=len(rejected_items),
        rows=rows_out, server_valid=len(run["valid"]), overflow=len(run["overflow"]),
        saved=bool(save), load_id=load_id,
    )


@app.route("/grid/generate", methods=["POST"])
def grid_generate():
    return _produce_load(save=False)


@app.route("/grid/save", methods=["POST"])
def grid_save():
    return _produce_load(save=True)


@app.route("/download/<run_id>/f/<path:name>")
def download_named(run_id, name):
    """הורדת קובץ ספציפי לפי שם (לקבצי אב/מסכי-משנה)."""
    if not _RUN_ID_RE.match(run_id) or "/" in name or "\\" in name or name.startswith("."):
        abort(404)
    run_dir = os.path.join(WEB_OUTPUT, run_id)
    if not os.path.isfile(os.path.join(run_dir, name)):
        abort(404)
    return send_from_directory(run_dir, name, as_attachment=True)


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


HISTORY = """
<!doctype html><html lang="he" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>היסטוריית טעינות</title>
<script>(function(){try{var t=localStorage.getItem('fl-theme');if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}})();</script>
<link href="https://fonts.googleapis.com/css2?family=Assistant:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
 :root{--bg:#eef2f9;--surface:#fff;--surface-2:#f7f9fc;--border:#e5eaf2;--text:#0f172a;--muted:#64748b;--brand:#4f46e5;
  --ok-fg:#166534;--bad-fg:#dc2626;--shadow:0 1px 2px rgba(16,24,40,.05),0 10px 30px rgba(16,24,40,.07);}
 @media (prefers-color-scheme:dark){:root:not([data-theme]){--bg:#0b1120;--surface:#111a2e;--surface-2:#0f1728;--border:#233047;--text:#e8edf6;--muted:#93a1b8;--brand:#818cf8;--ok-fg:#34d399;--bad-fg:#f87171;}}
 :root[data-theme="dark"]{--bg:#0b1120;--surface:#111a2e;--surface-2:#0f1728;--border:#233047;--text:#e8edf6;--muted:#93a1b8;--brand:#818cf8;--ok-fg:#34d399;--bad-fg:#f87171;}
 *{box-sizing:border-box}body{margin:0;font-family:"Assistant",-apple-system,"Segoe UI",system-ui,Arial,sans-serif;background:var(--bg);color:var(--text)}
 .wrap{max-width:1100px;margin:0 auto;padding:26px 18px 70px}
 .head{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
 h1{font-size:22px;font-weight:800;margin:0}
 a.back{color:var(--brand);text-decoration:none;font-weight:700}
 .card{background:var(--surface);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow);overflow:hidden}
 table{border-collapse:collapse;width:100%;font-size:14px}
 th,td{text-align:right;padding:11px 14px;border-bottom:1px solid var(--border);white-space:nowrap}
 th{background:var(--surface-2);font-weight:700}
 .ok{color:var(--ok-fg);font-weight:700}.bad{color:var(--bad-fg);font-weight:700}
 .dl{color:var(--brand);text-decoration:none;font-weight:600;margin-left:10px}
 .dl.open{color:#fff;background:var(--brand);padding:5px 11px;border-radius:8px}
 .delbtn{background:none;border:1px solid var(--border);border-radius:8px;cursor:pointer;font-size:14px;padding:4px 8px;color:var(--bad-fg);width:auto}
 .delbtn:hover{background:rgba(220,38,38,.1);border-color:var(--bad-fg)}
 .empty{padding:40px;text-align:center;color:var(--muted)}
 .tag{font-size:12px;color:var(--muted)}
</style></head><body><div class="wrap">
 <div class="head"><h1>📜 היסטוריית טעינות</h1><a class="back" href="/">→ חזרה</a></div>
 {% if dbinfo %}
 <div style="margin-bottom:14px;font-size:13px;padding:11px 15px;border-radius:12px;
   border:1px solid var(--border);
   background:{{ 'rgba(5,150,105,.09)' if (dbinfo.ok and (dbinfo.backend=='postgres' or not dbinfo.vercel)) else 'rgba(220,38,38,.08)' }}">
  {% if dbinfo.backend=='postgres' and dbinfo.ok %}
   ✅ מסד נתונים: <b>Postgres</b> — מחובר ושומר לצמיתות ({{ dbinfo.count }} רשומות).
  {% elif dbinfo.backend=='postgres' and not dbinfo.ok %}
   ⛔ מסד נתונים: <b>Postgres</b> מוגדר אך אין חיבור — {{ dbinfo.error }}
  {% elif dbinfo.vercel %}
   ⚠️ מסד נתונים: <b>SQLite זמני</b> (‎/tmp‎) — <b>ההיסטוריה לא תישמר ב-Vercel</b>.
   חבר מסד Postgres (Storage → Create Database) ועשה Redeploy. ראה VERCEL.md.
  {% else %}
   ✅ מסד נתונים: <b>SQLite</b> ({{ dbinfo.count }} רשומות).
  {% endif %}
 </div>
 {% endif %}
 <div class="card">
 <form method="get" style="display:flex;gap:10px;align-items:center;margin-bottom:14px;flex-wrap:wrap">
  <label style="margin:0;font-weight:600">סינון לפי מסך:</label>
  <select name="screen" onchange="this.form.submit()"
   style="padding:8px 12px;border:1.5px solid var(--border);border-radius:10px;background:var(--surface-2);color:var(--text);font:inherit">
   <option value="">— כל המסכים —</option>
   {% for s in screens %}<option value="{{ s }}" {% if s==sel_screen %}selected{% endif %}>{{ s }}</option>{% endfor %}
  </select>
  <span class="tag">{{ rows|length }} רשומות</span>
 </form>
 {% if not rows %}<div class="empty">עדיין לא בוצעו טעינות.</div>
 {% else %}
 <table><thead><tr><th>זמן</th><th>מסך</th><th>קובץ מקור</th><th>נקראו</th><th>תקינות</th><th>נפסלו</th><th>אזהרות</th><th>משתמש</th><th>קבצים</th><th></th></tr></thead><tbody>
 {% for r in rows %}
 <tr>
  <td class="tag">{{ r.ts }}</td><td>{{ r.screen }}</td><td>{{ r.source or '—' }}</td>
  <td>{{ r.total }}</td><td class="ok">{{ r.valid }}</td>
  <td class="{{ 'bad' if r.invalid else '' }}">{{ r.invalid }}</td><td>{{ r.warnings }}</td>
  <td class="tag">{{ r.user or '' }}{% if r.via=='cli' %} · CLI{% endif %}</td>
  <td>{% if r.has_snapshot %}<a class="dl open" href="/history/open/{{ r.id }}">↗ פתח טבלה</a>{% endif %}
      {% for f in r.files %}<a class="dl" href="/history/file/{{ f.id }}">{{ f.label }}</a>{% endfor %}
      {% if not r.files and not r.has_snapshot %}<span class="tag">—</span>{% endif %}</td>
  <td><form method="post" action="/history/delete/{{ r.id }}" style="margin:0"
        onsubmit="return confirm('למחוק את רשומת הטעינה של {{ (r.source or r.screen)|e }}?')">
        <button type="submit" class="delbtn" title="מחק מההיסטוריה">🗑</button></form></td>
 </tr>
 {% endfor %}
 </tbody></table>
 {% endif %}
 </div>
</div></body></html>
"""


@app.route("/history")
def history():
    screen = (request.args.get("screen") or "").strip() or None
    return render_template_string(
        HISTORY, rows=core.read_history(300, screen=screen),
        screens=db.distinct_screens(), sel_screen=screen or "", dbinfo=db.status())


@app.route("/history/open/<int:load_id>")
def history_open(load_id):
    """פותח מחדש את טבלת הטעינה שנשמרה — משחזר את השורות והעריכות."""
    raw = db.get_snapshot(load_id)
    if not raw:
        return _upload_error("לא נמצאה תמונת-טבלה לטעינה זו (נשמרה לפני הוספת התכונה?).")
    import json
    try:
        snap = json.loads(raw.decode("utf-8"))
        screen = snap["screen"]
        mapping = core.load_mapping(screen)
        df = pd.DataFrame(snap.get("rows") or [])
        # העמודות כבר בשמות ה-target; ממפים כל target לעמודה בעלת אותו שם
        overrides = {c["target"]: c["target"]
                     for c in core.all_columns(mapping) if c["target"] in df.columns}
        payload = _build_grid(screen, mapping, df, overrides=overrides,
                              source_name=snap.get("source_name") or "")
    except core.UserError as e:
        return _upload_error(str(e))
    except Exception as e:  # noqa: BLE001
        return _upload_error(f"שגיאה בפתיחת הטבלה מההיסטוריה:\n{e}")
    return render_template_string(GRID, screen=screen, grid=payload, brand=brand_html())


@app.route("/history/delete/<int:load_id>", methods=["POST"])
def history_delete(load_id):
    db.delete_load(load_id)
    return redirect("/history")


@app.route("/history/file/<int:file_id>")
def history_file(file_id):
    name, content = db.get_file(file_id)
    if content is None:
        abort(404)
    from flask import Response
    resp = Response(content, mimetype="application/octet-stream")
    resp.headers["Content-Disposition"] = f"attachment; filename={name or 'file'}"
    return resp


# ---------------------------------------------------------------------------
# מסך שערי בנק ישראל — אימות שליפת הנתונים החיה מ-BoI
# ---------------------------------------------------------------------------
# רשימת מטבעות ברירת מחדל להצגה (מול השקל). ניתן להוסיף/להסיר במסך.
_DEFAULT_RATE_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD"]


def _currency_desc_map():
    return {code: desc for code, desc in core.lookup_pairs("currencies")}


RATES = """
<!doctype html><html lang="he" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>שערי בנק ישראל — אימות משיכת נתונים</title>
<script>(function(){try{var t=localStorage.getItem('fl-theme');if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}})();</script>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Assistant:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
 :root{--bg:#eef2f9;--surface:#fff;--surface-2:#f7f9fc;--border:#e5eaf2;--text:#0f172a;--muted:#64748b;
  --brand:#4f46e5;--brand-2:#6366f1;--green:#059669;--red:#dc2626;--amber:#b45309;--radius:18px;
  --shadow:0 1px 2px rgba(16,24,40,.05),0 8px 24px rgba(16,24,40,.07);}
 @media (prefers-color-scheme:dark){:root:not([data-theme]){--bg:#0b1120;--surface:#111a2e;--surface-2:#0f1728;--border:#233047;
  --text:#e8edf6;--muted:#93a1b8;--brand:#818cf8;--brand-2:#a5b4fc;--green:#34d399;--red:#f87171;--amber:#fbbf24;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 30px rgba(0,0,0,.4);}}
 :root[data-theme="dark"]{--bg:#0b1120;--surface:#111a2e;--surface-2:#0f1728;--border:#233047;
  --text:#e8edf6;--muted:#93a1b8;--brand:#818cf8;--brand-2:#a5b4fc;--green:#34d399;--red:#f87171;--amber:#fbbf24;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 30px rgba(0,0,0,.4);}
 .brand{display:flex;align-items:center;gap:11px}.brand .logo-img{height:46px;width:auto}
 .brand-tx{display:flex;flex-direction:column;line-height:1.05}
 .brand-name{font-weight:800;font-size:21px;color:var(--text)}.brand-sub{font-weight:600;font-size:12.5px;color:#1e50c8}
 *{box-sizing:border-box}
 body{margin:0;min-height:100vh;color:var(--text);line-height:1.6;
  font-family:"Assistant",-apple-system,"Segoe UI",system-ui,Arial,sans-serif;
  background:radial-gradient(1100px 500px at 100% -10%,rgba(99,102,241,.18),transparent 60%),
   radial-gradient(900px 500px at -10% 0%,rgba(16,185,129,.12),transparent 55%),var(--bg);}
 .wrap{max-width:900px;margin:0 auto;padding:26px 20px 70px}
 .topbar{display:flex;align-items:center;justify-content:space-between;margin:0 auto 18px}
 .themebtn{background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:10px;
  padding:8px 12px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;text-decoration:none}
 .themebtn:hover{background:var(--surface-2)}
 .hero{text-align:center;margin-bottom:22px}
 .logo{width:58px;height:58px;border-radius:18px;margin:0 auto 14px;display:grid;place-items:center;
  font-size:28px;color:#fff;background:linear-gradient(140deg,var(--brand-2),var(--brand));box-shadow:0 10px 24px rgba(79,70,229,.4)}
 h1{font-size:26px;font-weight:800;margin:0 0 6px;letter-spacing:-.02em}.hero p{color:var(--muted);margin:0}
 .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:22px;box-shadow:var(--shadow);margin-bottom:18px}
 label{display:block;font-weight:600;margin:0 0 7px;font-size:14px}
 input[type=date],input[type=text]{width:100%;padding:11px 13px;border:1.5px solid var(--border);border-radius:12px;
  font-size:15px;font-family:inherit;background:var(--surface-2);color:var(--text)}
 input:focus{outline:none;border-color:var(--brand);box-shadow:0 0 0 4px rgba(99,102,241,.15);background:var(--surface)}
 .row{display:flex;gap:14px;flex-wrap:wrap;align-items:flex-end}.row>div{flex:1;min-width:180px}
 .chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px}
 .chip{display:inline-flex;align-items:center;gap:6px;background:var(--surface-2);border:1.5px solid var(--border);
  border-radius:999px;padding:7px 13px;font-size:13.5px;font-weight:600;cursor:pointer;user-select:none;transition:.12s}
 .chip.on{background:rgba(99,102,241,.14);border-color:var(--brand);color:var(--brand)}
 .chip small{color:var(--muted);font-weight:500}
 button.go{width:auto;background:linear-gradient(140deg,var(--brand-2),var(--brand));color:#fff;border:0;border-radius:12px;
  padding:13px 26px;font-size:15px;font-weight:700;cursor:pointer;box-shadow:0 8px 20px rgba(79,70,229,.32);font-family:inherit}
 button.go:hover{transform:translateY(-1px)}button.go:disabled{opacity:.6;cursor:default;transform:none}
 table{border-collapse:collapse;width:100%;font-size:14.5px}
 th,td{text-align:right;padding:12px 14px;border-bottom:1px solid var(--border);white-space:nowrap}
 th{background:var(--surface-2);font-weight:700;position:sticky;top:0}
 td.rate{font-weight:800;font-variant-numeric:tabular-nums;font-size:16px}
 .ok{color:var(--green);font-weight:700}.bad{color:var(--red);font-weight:700}.warn{color:var(--amber);font-weight:700}
 .muted{color:var(--muted);font-size:13px}
 .note{background:rgba(99,102,241,.07);border:1px solid var(--border);border-radius:12px;padding:12px 15px;color:var(--muted);font-size:13px;margin-top:12px}
 .spin{display:inline-block;width:15px;height:15px;border:2px solid rgba(255,255,255,.5);border-top-color:#fff;border-radius:50%;animation:sp .7s linear infinite;vertical-align:-2px;margin-left:7px}
 @keyframes sp{to{transform:rotate(360deg)}}
 code{background:var(--surface-2);border:1px solid var(--border);padding:2px 7px;border-radius:6px;font-size:12.5px;direction:ltr;display:inline-block}
 a.back{color:var(--brand);text-decoration:none;font-weight:700}
 .empty{padding:34px;text-align:center;color:var(--muted)}
</style></head><body><div class="wrap">
 <div class="topbar">{{ brand|safe }}
  <div style="display:flex;gap:8px;align-items:center">
   <a class="themebtn" href="/">→ חזרה לטעינה</a>
   <button id="themebtn" class="themebtn" onclick="toggleTheme()">🌙 מצב כהה</button></div></div>
 <div class="hero"><div class="logo">💱</div>
  <h1>שערי בנק ישראל</h1>
  <p>משיכה חיה מ-API של בנק ישראל (מול השקל) — לאימות שהנתונים נמשכים כראוי.</p></div>

 <div class="card">
  <div class="row">
   <div><label for="rdate">תאריך</label><input type="date" id="rdate"></div>
   <div style="flex:none"><button class="go" id="gobtn" onclick="fetchRates()">משוך שערים ←</button></div>
  </div>
  <label style="margin-top:16px">מטבעות</label>
  <div class="chips" id="chips"></div>
  <div class="row" style="margin-top:12px">
   <div><label for="addcur">הוספת מטבע (קוד ISO, למשל SEK)</label>
    <input type="text" id="addcur" placeholder="קוד מטבע" maxlength="3"
     onkeydown="if(event.key==='Enter'){addCur();event.preventDefault();}"></div>
  </div>
 </div>

 <div class="card"><div id="results"><div class="empty">בחר תאריך ומטבעות ולחץ "משוך שערים".</div></div>
  <div class="note">מקור: בנק ישראל (EDGE / SDMX). אם אין פרסום לתאריך המבוקש (סופ"ש/חג) —
   נלקח השער הזמין האחרון עד 7 ימים אחורה, והתאריך בפועל מוצג בעמודה נפרדת.</div>
 </div>
</div><script>
 const DEFAULT={{ currencies|tojson }};
 const DESC={{ desc|tojson }};
 let picked=new Set(DEFAULT);
 const $=id=>document.getElementById(id);
 function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
 function today(){const d=new Date();return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');}
 function renderChips(){
  $('chips').innerHTML=[...picked].map(c=>
   '<span class="chip on" onclick="toggle(\\''+esc(c)+'\\')">'+esc(c)+
   (DESC[c]?' <small>'+esc(DESC[c])+'</small>':'')+' ✕</span>').join('');
 }
 function toggle(c){picked.delete(c);renderChips();}
 function addCur(){let v=($('addcur').value||'').trim().toUpperCase();if(!v)return;picked.add(v);$('addcur').value='';renderChips();}
 async function fetchRates(){
  const curs=[...picked];
  if(!curs.length){$('results').innerHTML='<div class="empty bad">בחר לפחות מטבע אחד.</div>';return;}
  const btn=$('gobtn');btn.disabled=true;const old=btn.innerHTML;btn.innerHTML='מושך<span class="spin"></span>';
  $('results').innerHTML='<div class="empty">מושך שערים מבנק ישראל…</div>';
  try{
   const r=await fetch('/rates/fetch',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({date:$('rdate').value,currencies:curs})});
   const j=await r.json();
   if(!r.ok||j.error){$('results').innerHTML='<div class="empty bad">שגיאה: '+esc(j.error||r.status)+'</div>';return;}
   render(j);
  }catch(e){$('results').innerHTML='<div class="empty bad">תקלה בתקשורת: '+esc(e)+'</div>';}
  finally{btn.disabled=false;btn.innerHTML=old;}
 }
 function render(j){
  let h='<div style="overflow-x:auto"><table><thead><tr><th>מטבע</th><th>שם</th><th>שער (₪)</th>'+
        '<th>תאריך בפועל</th><th>סטטוס</th></tr></thead><tbody>';
  j.rates.forEach(x=>{
   const fb=x.effective && j.requested && x.effective!==j.requested;
   let st = x.rate==null ? '<span class="bad">לא נמצא</span>'
          : (fb ? '<span class="warn">שער קודם (fallback)</span>' : '<span class="ok">✓ תקין</span>');
   h+='<tr><td><code>'+esc(x.currency)+'</code></td><td>'+esc(x.desc||'')+'</td>'+
      '<td class="rate">'+(x.rate==null?'—':esc(x.rate))+'</td>'+
      '<td class="muted">'+esc(x.effective||'—')+'</td><td>'+st+'</td></tr>';
  });
  h+='</tbody></table></div>';
  const ok=j.rates.filter(x=>x.rate!=null).length;
  h+='<p class="muted" style="margin:14px 2px 0">נמשכו '+ok+' מתוך '+j.rates.length+
     ' שערים · תאריך מבוקש: '+esc(j.requested||'—')+'</p>';
  $('results').innerHTML=h;
 }
 function toggleTheme(){var r=document.documentElement,cur=r.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
  var nx=cur==='dark'?'light':'dark';r.setAttribute('data-theme',nx);try{localStorage.setItem('fl-theme',nx);}catch(e){}updateThemeBtn();}
 function updateThemeBtn(){var b=$('themebtn');if(!b)return;
  var cur=document.documentElement.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
  b.textContent=cur==='dark'?'☀️ מצב בהיר':'🌙 מצב כהה';}
 $('rdate').value=today();updateThemeBtn();renderChips();
</script></body></html>
"""


@app.route("/rates")
def rates_page():
    return render_template_string(
        RATES, brand=brand_html(),
        currencies=_DEFAULT_RATE_CURRENCIES, desc=_currency_desc_map())


@app.route("/rates/fetch", methods=["POST"])
def rates_fetch():
    data = request.get_json(silent=True) or {}
    date = (data.get("date") or "").strip() or None
    currencies = [str(c).strip().upper() for c in (data.get("currencies") or []) if str(c).strip()]
    currencies = list(dict.fromkeys(currencies))[:30]   # ייחודיים, תקרה בטיחותית
    if not currencies:
        return jsonify(error="לא נבחרו מטבעות."), 400
    descs = _currency_desc_map()
    requested = None
    if date:
        try:
            requested = boi._to_date(date).strftime("%Y-%m-%d")
        except ValueError:
            return jsonify(error=f"תאריך לא תקין: {date}"), 400
    out = []
    for cur in currencies:
        try:
            rate, effective = boi.get_rate(cur, date)
        except Exception:  # noqa: BLE001 — כשל רשת/פירוק לא יפיל את המסך
            rate, effective = None, None
        out.append({"currency": cur, "desc": descs.get(cur, ""),
                    "rate": rate, "effective": effective})
    return jsonify(requested=requested, rates=out)


LOGIN = """
<!doctype html><html lang="he" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>התחברות — Priority ERP</title>
<script>(function(){try{var t=localStorage.getItem('fl-theme');if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}})();</script>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Assistant:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
 :root{--bg:#eef2f9;--surface:#fff;--surface-2:#f7f9fc;--border:#e5eaf2;--text:#0f172a;--muted:#64748b;
  --brand:#4f46e5;--brand-2:#6366f1;--red:#dc2626;--radius:18px;--shadow:0 20px 50px rgba(37,40,90,.16);}
 @media (prefers-color-scheme:dark){:root:not([data-theme]){--bg:#0b1120;--surface:#111a2e;--surface-2:#0f1728;--border:#233047;
  --text:#e8edf6;--muted:#93a1b8;--brand:#818cf8;--brand-2:#a5b4fc;--red:#f87171;--shadow:0 24px 60px rgba(0,0,0,.55);}}
 :root[data-theme="dark"]{--bg:#0b1120;--surface:#111a2e;--surface-2:#0f1728;--border:#233047;
  --text:#e8edf6;--muted:#93a1b8;--brand:#818cf8;--brand-2:#a5b4fc;--red:#f87171;--shadow:0 24px 60px rgba(0,0,0,.55);}
 .brand{display:flex;align-items:center;gap:11px;justify-content:center;margin-bottom:20px}
 .brand .logo-img{height:46px;width:auto}.brand-tx{display:flex;flex-direction:column;line-height:1.05;text-align:right}
 .brand-name{font-weight:800;font-size:21px;color:var(--text)}.brand-sub{font-weight:600;font-size:12.5px;color:#1e50c8}
 *{box-sizing:border-box}
 body{margin:0;min-height:100vh;display:grid;place-items:center;color:var(--text);
  font-family:"Assistant",-apple-system,"Segoe UI",system-ui,Arial,sans-serif;
  background:radial-gradient(1100px 500px at 100% -10%,rgba(99,102,241,.18),transparent 60%),
   radial-gradient(900px 500px at -10% 0%,rgba(16,185,129,.12),transparent 55%),var(--bg);}
 .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  padding:34px 30px;box-shadow:var(--shadow);width:min(400px,92vw)}
 .logo{width:56px;height:56px;border-radius:16px;margin:0 auto 14px;display:grid;place-items:center;
  font-size:26px;color:#fff;background:linear-gradient(140deg,var(--brand-2),var(--brand));box-shadow:0 10px 24px rgba(79,70,229,.4)}
 h1{font-size:22px;font-weight:800;margin:0 0 4px;text-align:center}
 .sub{color:var(--muted);text-align:center;margin:0 0 22px;font-size:14px}
 label{display:block;font-weight:600;margin:14px 0 6px;font-size:14px}
 input{width:100%;padding:12px 13px;border:1.5px solid var(--border);border-radius:12px;font-size:15px;
  font-family:inherit;background:var(--surface-2);color:var(--text)}
 input:focus{outline:none;border-color:var(--brand);box-shadow:0 0 0 4px rgba(99,102,241,.15);background:var(--surface)}
 button{width:100%;margin-top:22px;background:linear-gradient(140deg,var(--brand-2),var(--brand));color:#fff;border:0;
  border-radius:12px;padding:13px;font-size:16px;font-weight:700;cursor:pointer;box-shadow:0 8px 20px rgba(79,70,229,.32);font-family:inherit}
 button:hover{transform:translateY(-1px)}
 .err{background:rgba(220,38,38,.09);border:1px solid rgba(220,38,38,.32);color:var(--red);
  border-radius:12px;padding:11px 14px;font-size:13.5px;margin-top:16px;text-align:center}
</style></head><body>
 <form class="card" method="post" action="/login">
  {{ brand|safe }}
  <div class="logo">🔒</div>
  <h1>התחברות למערכת</h1>
  <p class="sub">הכנת קבצי טעינה ל-Priority ERP</p>
  <input type="hidden" name="next" value="{{ next }}">
  <label for="username">שם משתמש</label>
  <input id="username" name="username" autocomplete="username" autofocus>
  <label for="password">סיסמה</label>
  <input id="password" name="password" type="password" autocomplete="current-password">
  {% if error %}<div class="err">❌ {{ error }}</div>{% endif %}
  <button type="submit">התחבר ←</button>
 </form>
</body></html>
"""


@app.route("/login", methods=["GET", "POST"])
def login():
    if not AUTH_PASS:            # אימות כבוי — אין מסך התחברות
        return redirect("/")
    nxt = request.values.get("next") or "/"
    if not nxt.startswith("/"):  # מניעת open-redirect — רק נתיבים פנימיים
        nxt = "/"
    error = None
    if request.method == "POST":
        user_ok = hmac.compare_digest(request.form.get("username", ""), AUTH_USER)
        pass_ok = hmac.compare_digest(request.form.get("password", ""), AUTH_PASS)
        if user_ok and pass_ok:
            session["auth"] = True
            session["user"] = AUTH_USER
            return redirect(nxt)
        error = "שם משתמש או סיסמה שגויים."
    return render_template_string(LOGIN, brand=brand_html(), error=error, next=nxt)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


def _upload_error(msg):
    return render_template_string(UPLOAD, screens=core.available_screens(), error=msg,
                                  brand=brand_html(), auth_on=_auth_on())


if __name__ == "__main__":
    os.makedirs(WEB_OUTPUT, exist_ok=True)
    print("=" * 56)
    print("  ממשק הכנת קבצי טעינה לפריוריטי פועל")
    print("  פתח בדפדפן:  http://127.0.0.1:5000")
    print("  לעצירה: Ctrl+C")
    print("=" * 56)
    app.run(host="127.0.0.1", port=5000, debug=False)
