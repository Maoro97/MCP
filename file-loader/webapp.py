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
  <button id="themebtn" class="themebtn" onclick="toggleTheme()">🌙 מצב כהה</button></div>
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
   <label>קובץ האקסל</label>
   <div class="drop" id="drop"><span class="ico">📄</span><b>גרור לכאן קובץ</b> או לחץ לבחירה<small>קבצי .xlsx בלבד</small>
    <input type="file" id="file" name="file" accept=".xlsx" hidden required>
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
 .spacer{flex:1}a.back{color:var(--brand);text-decoration:none;font-weight:700;font-size:14px}
 .chk{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--muted);cursor:pointer}.chk input{width:16px;height:16px;accent-color:var(--brand)}
 .banner{background:rgba(99,102,241,.08);border:1px solid rgba(99,102,241,.25);color:var(--brand);border-radius:12px;padding:11px 15px;margin:8px 0;font-size:14px}
 .tablewrap{overflow-x:auto;border:1px solid var(--border);border-radius:16px;background:var(--surface);box-shadow:var(--shadow)}
 table{border-collapse:separate;border-spacing:0;width:100%;font-size:14px}
 th,td{border-bottom:1px solid var(--border);border-left:1px solid var(--border);padding:0;text-align:right;white-space:nowrap}
 th{background:var(--surface-2);padding:10px 12px;position:sticky;top:0;z-index:2}
 th .tgt{font-weight:700}th .src{display:block;font-weight:400;color:var(--muted);font-size:11.5px}
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
 .msg.ok{background:var(--ok-bg);color:var(--ok-fg)}.msg.err{background:var(--bad-bg);color:var(--bad-fg)}
 .msg.warnbox{background:var(--warn-bg);color:var(--warn-fg);border:1px solid rgba(217,119,6,.3);font-weight:500}
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
 .mapitem select{padding:8px 10px;border:1.5px solid var(--border);border-radius:9px;background:var(--surface-2);color:var(--text);font-family:inherit;font-size:13.5px}
 .mapitem.mapreq select{border-color:var(--bad-fg)}
 .mapitem select:focus{outline:none;border-color:var(--brand);box-shadow:0 0 0 3px rgba(99,102,241,.15)}
</style></head><body><div class="wrap">
 <div class="apphead">
  <div class="ttl"><h1>📋 טבלת טעינה — מסך {{ screen }}</h1>
   <p class="sub">תקן תאים מסומנים (רחף לראות סיבה), מחק או התעלם משורות, סדר עמודות בגרירה — ואז הפק את קובץ הטעינה.</p></div>
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
  <label class="chk" id="filterwrap"><input type="checkbox" id="onlyerr" onchange="render()"> הצג רק שורות לטיפול</label>
  <button class="b-check" onclick="ignoreAllWarnings()" title="סמן את כל שורות האזהרה כמיוצאות">🚫 התעלם מאזהרות</button>
  <button class="b-check" onclick="revalidate()">🔄 בדוק מחדש</button>
  <button class="b-gen" onclick="generate()">⬇ צור קובץ טעינה</button>
  <a class="back" href="/">＋ קובץ חדש</a>
 </div>
 <div id="banner"></div><div id="mapping"></div><div id="messages"></div>
 <div class="legend">
  <span><i class="sw-bad"></i>תא שגוי לתיקון</span>
  <span><i class="sw-warn"></i>אזהרה (לא פוסל — כלול בטעינה)</span>
  <span><i class="sw-const"></i>ערך קבוע (לא לעריכה)</span>
  <span><i class="sw-ign"></i>מיוצא למרות בעיה (🚫)</span>
  <span class="hint">🗑 מוחק שורה · 🚫 מייצא למרות בעיה · ⋮⋮ גרור כותרת לשינוי סדר · ↔ גרור את קצה הכותרת לשינוי רוחב · תאריך dd/mm/yy</span>
 </div>
 <div class="tablewrap"><table id="grid"></table></div>
 <div class="pager" id="pager"></div>
 <p class="hint" id="dlarea"></p>
<script>
const GRID = {{ grid|tojson }};
const PAGE_SIZE = 100;
let page = 0;
let colOrder = GRID.columns.map((_, i) => i);   // סדר תצוגה/ייצוא של העמודות
let colWidths = {};                             // רוחב מותאם לעמודה (ci -> px)
const $ = id => document.getElementById(id);

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
  const onlyErr = $('onlyerr').checked;
  const out=[];
  GRID.rows.forEach((r,gi)=>{
    // "לטיפול" = יש בעיה ולא סומן להתעלמות
    const attention = !r.ignore && (!r.valid || r.cells.some(c=>c.warning));
    if(!onlyErr || attention) out.push([gi,r]);
  });
  return out;
}
function render(){
  const cols=GRID.columns, disp=displayed();
  const pages=Math.max(1,Math.ceil(disp.length/PAGE_SIZE));
  if(page>=pages) page=pages-1; if(page<0) page=0;
  const slice=disp.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE);
  let h='<thead><tr><th class="act"></th><th class="rownum">#</th>';
  for(const ci of colOrder){ const c=cols[ci];
    const w=colWidths[ci]?' style="min-width:'+colWidths[ci]+'px"':'';
    h+='<th class="col" draggable="true" data-ci="'+ci+'"'+w+' ondragstart="dragStart(event,'+ci+
       ')" ondragover="dragOver(event)" ondragleave="dragLeave(event)" ondrop="dropCol(event,'+ci+
       ')" ondragend="dragEnd(event)"><span class="rez" title="גרור לשינוי רוחב" onmousedown="startResize(event,'+ci+
       ')"></span><span class="grip">⋮⋮</span><span class="tgt">'+esc(c.target)+
       '</span><span class="src">'+(c.constant?'ערך קבוע':esc(c.source||''))+'</span></th>';
  }
  h+='</tr></thead><tbody>';
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
      h+='<td class="'+cls+'"'+title+'><input data-ci="'+ci+'" value="'+esc(cell.value)+'"'+ro+wst+
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
  const warned=GRID.rows.filter(r=>!r.ignore && r.cells.some(c=>c.warning)).length;
  $('p-warn').textContent='אזהרות '+warned; $('p-warn').style.display = warned? '' : 'none';
  const ign=GRID.rows.filter(r=>r.ignore).length;
  $('p-ign').textContent='מיוצאות למרות בעיה '+ign; $('p-ign').style.display = ign? '' : 'none';
}
function upd(gi,ci,val){ GRID.rows[gi].cells[ci].value=val; }
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
    h+='<label class="mapitem'+(bad?' mapreq':'')+'"><span class="mapt">'+esc(c.target)+
       (bad?' • חובה':'')+'</span><select data-t="'+esc(c.target)+'" onchange="remap()">'+
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
async function revalidate(){
  const res=await post('/grid/validate',collect()); if(!res)return;
  GRID.rows=keepIgnore(res.rows); render();
  const o=overall();
  flash(o.invalid===0?'ok':'err', o.invalid===0?'✓ כל השורות תקינות — אפשר לייצר קובץ טעינה.':
        'נותרו '+o.invalid+' שורות עם שגיאות לתיקון.');
}
async function generate(){
  const res=await post('/grid/generate',collect()); if(!res)return;
  if(res.rows){ GRID.rows=keepIgnore(res.rows); GRID.server_valid=res.server_valid; GRID.overflow=res.overflow; render(); }
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

function toggleTheme(){var r=document.documentElement,cur=r.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
  var nx=cur==='dark'?'light':'dark';r.setAttribute('data-theme',nx);try{localStorage.setItem('fl-theme',nx);}catch(e){}updateThemeBtn();}
function updateThemeBtn(){var b=$('themebtn');if(!b)return;
  var cur=document.documentElement.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
  b.textContent=cur==='dark'?'☀️ מצב בהיר':'🌙 מצב כהה';}

if(GRID.mode==='errors') $('onlyerr').checked=true;
updateThemeBtn(); renderBanner(); renderMapping(); render();
</script></body></html>
"""


# ---------------------------------------------------------------------------
# נתיבים
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template_string(UPLOAD, screens=core.available_screens(), error=None, brand=brand_html())


def _build_grid(screen, mapping, df, overrides, run_id=None):
    """
    ליבת בניית תגובת הטבלה — משותפת ל-/process ול-/grid/remap.
    פותר את המיפוי (עם overrides ידניים), מריץ ולידציה, מפצל קטן/גדול, שומר את
    הריצה (כולל ה-DataFrame הגולמי כדי לאפשר מיפוי מחדש), ומחזיר payload מלא.
    """
    resolved, req_missing, opt_missing = core.resolve_columns(df, mapping["columns"], overrides)
    rows_out = core.evaluate_grid(mapping, core.rows_from_dataframe(df, mapping, resolved))
    key_fields = mapping.get("key_fields") or []
    total = len(rows_out)

    def _has_warn(r):
        return any(c.get("warning") for c in r["cells"])

    invalid_rows = [r for r in rows_out if not r["valid"]]
    valid_rows = [r for r in rows_out if r["valid"]]

    if total <= FULL_GRID_LIMIT:
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

    run_id = run_id or uuid.uuid4().hex
    RUNS[run_id] = {
        "screen": screen, "df": df, "overrides": dict(overrides or {}),
        "valid": server_valid, "reserved": reserved, "overflow": overflow_items,
        "created": time.time(),
    }
    _prune_runs()

    warnings, warn_count = _sample_warnings(mapping, core.grid_valid_records(valid_rows))
    total_warn = sum(1 for r in rows_out if _has_warn(r))
    assignment = {
        c["target"]: resolved.get(c["target"], "")
        for c in mapping["columns"] if c.get("source") is not None
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
    }


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
        payload = _build_grid(screen, mapping, df, overrides=None)
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

    # "התעלם מבעיה" — שורות שסומנו ידנית ייכללו בייצוא למרות שגיאה/אזהרה
    ignore = data.get("ignore") or []
    for i, r in enumerate(rows_out):
        if i < len(ignore) and ignore[i]:
            r["valid"] = True
            r["forced"] = True

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
    return render_template_string(UPLOAD, screens=core.available_screens(), error=msg, brand=brand_html())


if __name__ == "__main__":
    os.makedirs(WEB_OUTPUT, exist_ok=True)
    print("=" * 56)
    print("  ממשק הכנת קבצי טעינה לפריוריטי פועל")
    print("  פתח בדפדפן:  http://127.0.0.1:5000")
    print("  לעצירה: Ctrl+C")
    print("=" * 56)
    app.run(host="127.0.0.1", port=5000, debug=False)
