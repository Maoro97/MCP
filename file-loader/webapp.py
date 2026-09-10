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


def _env_flag(name):
    return (os.environ.get(name, "") or "").strip().lower() in ("1", "true", "yes", "on")


# מפתח לחתימת ה-cookie של ההתחברות (session). ה-session נשמר בצד הלקוח כ-cookie
# חתום. חובה שהמפתח יהיה סודי — אחרת אפשר לזייף cookie ולעקוף התחברות. לכן אין
# ברירת-מחדל קבועה: אם לא הוגדר SECRET_KEY, נגריל מפתח אקראי לכל תהליך (בטוח, אבל
# ה-session לא ישרוד הפעלה-מחדש — לכן בענן חובה להגדיר SECRET_KEY לקביעוּת).
app.secret_key = os.environ.get("SECRET_KEY") or os.environ.get("APP_SECRET")
if not app.secret_key:
    import secrets as _secrets
    app.secret_key = _secrets.token_hex(32)
    _SECRET_RANDOM = True
else:
    _SECRET_RANDOM = False

# מסך התחברות: מופעל אם הוגדרה סיסמה ב-APP_PASSWORD. שם המשתמש: APP_USERNAME
# (ברירת מחדל admin).
AUTH_USER = os.environ.get("APP_USERNAME", "admin")
AUTH_PASS = os.environ.get("APP_PASSWORD")

# --- מדיניות אבטחה: fail-closed בענן ---
# פריסה ציבורית (Vercel/Render) *ללא* סיסמה = חשיפה מלאה של המערכת. במקום לשרת
# פתוח בשקט (fail-open), אנו חוסמים את הגישה ומציגים הודעת הגדרה — אלא אם המפעיל
# אישר פתיחוּת במפורש ב-ALLOW_OPEN=1. בהרצה מקומית — נשאר פתוח לנוחות.
_HOSTED = bool(os.environ.get("VERCEL") or os.environ.get("RENDER"))
_REQUIRE_AUTH = (_HOSTED or _env_flag("REQUIRE_AUTH")) and not _env_flag("ALLOW_OPEN")
AUTH_MISCONFIGURED = _REQUIRE_AUTH and not AUTH_PASS

# נתיבי JSON (נקראים ב-fetch) — עליהם נחזיר 401/503 במקום הפניה לעמוד התחברות
_AUTH_JSON_PREFIXES = ("/grid/", "/journal/", "/rates/fetch")
_AUTH_OPEN_ENDPOINTS = {"login", "logout", "static"}


@app.before_request
def _require_login():
    # פריסה בענן ללא סיסמה — חוסמים הכל (חוץ מקבצים סטטיים) עד להגדרת APP_PASSWORD.
    if AUTH_MISCONFIGURED:
        if request.endpoint == "static":
            return None
        if request.path.startswith(_AUTH_JSON_PREFIXES):
            return jsonify(error="האפליקציה פרוסה בענן ללא סיסמה. הגדר APP_PASSWORD "
                                 "(ו-SECRET_KEY) במשתני הסביבה ובצע Redeploy."), 503
        return render_template_string(CONFIG_ERROR, brand=brand_html()), 503
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


# ===========================================================================
# מערכת עיצוב משותפת (Design System) — מקור אמת אחד לכל המסכים.
# פלטה מונוכרומטית בהשראת Linear/Vercel: אפורים ניטרליים + אקסנט אחד מרוסן,
# ללא גרדיאנטים, אייקוני-קו (SVG) אחידים, פוקוס נגיש, ומצב כהה/בהיר.
# מוזרק לכל התבניות דרך context_processor (theme_css / icon / theme_js).
# ===========================================================================
import json as _json

# --- ספריית אייקונים (Lucide-style, stroke=currentColor) ---
_ICON_PATHS = {
    "moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4'
           'M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "history": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "rates": '<path d="M3 17l6-6 4 4 8-8"/><path d="M17 7h4v4"/>',
    "logout": '<path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/>'
              '<path d="M10 17l5-5-5-5"/><path d="M15 12H3"/>',
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>',
    "upload": '<path d="M12 13v8"/><path d="m8 17 4-4 4 4"/>'
              '<path d="M20 16.6A5 5 0 0 0 18 7h-1.3A8 8 0 1 0 4 15.3"/>',
    "file": '<path d="M14 3v5h5"/><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12'
            'a2 2 0 0 0 2-2V8Z"/>',
    "arrow-l": '<path d="M19 12H5"/><path d="m11 5-7 7 7 7"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a6 6 0 0 1 0 12h-4"/>',
    "filter-off": '<path d="M21 3H5l5.6 6.7"/><path d="M14 14v6l-4 2v-9"/><path d="m3 3 18 18"/>',
    "arrow-r": '<path d="M5 12h14"/><path d="m13 5 7 7-7 7"/>',
    "lock": '<rect x="4" y="10" width="16" height="11" rx="2"/>'
            '<path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "trash": '<path d="M4 7h16"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/>'
             '<path d="M6 7l1 13a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-13"/>',
    "pencil": '<path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17v3Z"/>'
              '<path d="M13.5 6.5l3 3"/>',
    "chevron-l": '<path d="m15 6-6 6 6 6"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "check-circle": '<circle cx="12" cy="12" r="9"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
    "download": '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
    "balance": '<path d="M12 3v18"/><path d="M7 7h10"/><path d="m5 7-3 6h6Z"/>'
               '<path d="m19 7-3 6h6Z"/><path d="M8 21h8"/>',
    "check-list": '<path d="M4 6h11"/><path d="M4 12h11"/><path d="M4 18h7"/>'
                  '<path d="m17 15 2 2 4-4"/>',
    "coins": '<circle cx="9" cy="9" r="6"/><path d="M21 15a6 6 0 0 1-9 5.2"/>'
             '<path d="M9 6.5v5M7.5 7.5h2.2a1 1 0 0 1 0 2H8a1 1 0 0 0 0 2h2.5"/>',
    "sparkle": '<path d="M12 3l1.8 4.9L18.7 10l-4.9 1.8L12 16.7l-1.8-4.9L5.3 10'
               'l4.9-2.1Z"/>',
    "alert": '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 2 18a2 2 0 0 0 1.7 3'
             'h16.6a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>',
}


def icon(name, size=18, cls=None):
    """מחזיר SVG של אייקון-קו אחיד (משתמש ב-currentColor, אז מקבל צבע מההקשר)."""
    p = _ICON_PATHS.get(name, "")
    c = f' class="{cls}"' if cls else ""
    return (f'<svg{c} width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="1.75" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{p}</svg>')


# --- טוקנים + רכיבים משותפים (מוזרק לתוך <style> בכל תבנית) ---
THEME_CSS = """
 :root{
  --bg:#fbfbfc; --surface:#ffffff; --surface-2:#f5f6f8; --surface-3:#eef0f3;
  --border:#e7e8ec; --border-strong:#d7d9df;
  --text:#17181b; --muted:#61646c; --faint:#8a8d95;
  --accent:#5b57d6; --accent-hover:#4b47c4; --accent-fg:#ffffff;
  --accent-soft:rgba(91,87,214,.10); --accent-border:rgba(91,87,214,.35);
  --green:#2f9e44; --green-soft:rgba(47,158,68,.12);
  --red:#e03131; --red-soft:rgba(224,49,49,.10);
  --amber:#e8850c; --amber-soft:rgba(232,133,12,.12);
  --r-sm:8px; --r:10px; --r-lg:14px;
  --shadow:0 1px 2px rgba(16,18,25,.04),0 2px 8px rgba(16,18,25,.05);
  --shadow-lg:0 12px 32px rgba(16,18,25,.10),0 2px 8px rgba(16,18,25,.05);
  --ring:0 0 0 3px var(--accent-soft);
 }
 @media (prefers-color-scheme:dark){:root:not([data-theme]){
  --bg:#0b0c0e; --surface:#131417; --surface-2:#191a1e; --surface-3:#212328;
  --border:#26282d; --border-strong:#33363c;
  --text:#edeef0; --muted:#9b9ea5; --faint:#71747b;
  --accent:#8b8ff7; --accent-hover:#9ea1f8; --accent-fg:#0b0c0e;
  --accent-soft:rgba(139,143,247,.14); --accent-border:rgba(139,143,247,.4);
  --green:#51cf66; --green-soft:rgba(81,207,102,.14);
  --red:#ff6b6b; --red-soft:rgba(255,107,107,.13);
  --amber:#fcc419; --amber-soft:rgba(252,196,25,.14);
  --shadow:0 1px 2px rgba(0,0,0,.4),0 4px 16px rgba(0,0,0,.35);
  --shadow-lg:0 16px 40px rgba(0,0,0,.55),0 4px 16px rgba(0,0,0,.4);
 }}
 :root[data-theme="dark"]{
  --bg:#0b0c0e; --surface:#131417; --surface-2:#191a1e; --surface-3:#212328;
  --border:#26282d; --border-strong:#33363c;
  --text:#edeef0; --muted:#9b9ea5; --faint:#71747b;
  --accent:#8b8ff7; --accent-hover:#9ea1f8; --accent-fg:#0b0c0e;
  --accent-soft:rgba(139,143,247,.14); --accent-border:rgba(139,143,247,.4);
  --green:#51cf66; --green-soft:rgba(81,207,102,.14);
  --red:#ff6b6b; --red-soft:rgba(255,107,107,.13);
  --amber:#fcc419; --amber-soft:rgba(252,196,25,.14);
  --shadow:0 1px 2px rgba(0,0,0,.4),0 4px 16px rgba(0,0,0,.35);
  --shadow-lg:0 16px 40px rgba(0,0,0,.55),0 4px 16px rgba(0,0,0,.4);
 }
 *{box-sizing:border-box}
 html{-webkit-text-size-adjust:100%}
 body{margin:0;min-height:100vh;background:var(--bg);color:var(--text);line-height:1.55;
  font-family:"Assistant",-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,Arial,sans-serif;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
  font-feature-settings:"cv01","ss01";letter-spacing:-.006em}
 svg{flex:none;vertical-align:middle}
 ::selection{background:var(--accent-soft)}
 /* --- מיתוג --- */
 .brand{display:flex;align-items:center;gap:10px}
 .brand .logo-img{height:38px;width:auto}
 .brand-tx{display:flex;flex-direction:column;line-height:1.08}
 .brand-name{font-weight:700;font-size:16px;color:var(--text);letter-spacing:-.02em}
 .brand-sub{font-weight:500;font-size:11.5px;color:var(--muted);letter-spacing:.01em}
 /* --- סרגל עליון --- */
 .topbar{display:flex;align-items:center;justify-content:space-between;gap:14px;
  height:56px;padding:0 20px;border-bottom:1px solid var(--border);
  background:color-mix(in srgb,var(--surface) 85%,transparent);
  backdrop-filter:saturate(1.4) blur(10px);position:sticky;top:0;z-index:40}
 .topnav{display:flex;align-items:center;gap:6px}
 .navbtn{display:inline-flex;align-items:center;gap:7px;height:34px;padding:0 11px;
  border-radius:var(--r-sm);border:1px solid transparent;background:transparent;
  color:var(--muted);font:inherit;font-size:13px;font-weight:500;cursor:pointer;
  text-decoration:none;transition:background .13s,color .13s,border-color .13s;white-space:nowrap}
 .navbtn:hover{background:var(--surface-2);color:var(--text);border-color:var(--border)}
 .navbtn svg{color:var(--faint);transition:color .13s}
 .navbtn:hover svg{color:var(--muted)}
 .navbtn.solid{border-color:var(--border);background:var(--surface)}
 /* --- כרטיס --- */
 .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);
  box-shadow:var(--shadow)}
 /* --- טפסים --- */
 label{display:block;font-weight:600;margin:0 0 7px;font-size:13px;color:var(--text)}
 input[type=text],input[type=number],input[type=search],input[type=password],select,textarea{
  width:100%;padding:9px 12px;border:1px solid var(--border-strong);border-radius:var(--r);
  font-size:14px;font-family:inherit;background:var(--surface);color:var(--text);
  transition:border-color .13s,box-shadow .13s}
 input::placeholder,textarea::placeholder{color:var(--faint)}
 input:focus,select:focus,textarea:focus{outline:none;border-color:var(--accent);box-shadow:var(--ring)}
 select{cursor:pointer;appearance:none;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%2361646c' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='m6 9 6 6 6-6'/></svg>");
  background-repeat:no-repeat;background-position:left 11px center;padding-left:34px}
 /* --- כפתורים --- */
 .btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;
  padding:10px 16px;border-radius:var(--r);border:1px solid var(--border-strong);
  background:var(--surface);color:var(--text);font:inherit;font-size:14px;font-weight:600;
  cursor:pointer;transition:background .13s,border-color .13s,transform .05s,box-shadow .13s}
 .btn:hover{background:var(--surface-2);border-color:var(--faint)}
 .btn:active{transform:translateY(.5px)}
 .btn:focus-visible{outline:none;box-shadow:var(--ring)}
 .btn-primary{background:var(--accent);border-color:var(--accent);color:var(--accent-fg);
  box-shadow:0 1px 2px rgba(16,18,25,.10)}
 .btn-primary:hover{background:var(--accent-hover);border-color:var(--accent-hover)}
 .btn-lg{padding:13px 20px;font-size:15px;width:100%}
 .btn svg{color:currentColor}
 /* --- כללי --- */
 .muted{color:var(--muted);font-size:13px}
 a{color:var(--accent)}
 .backlink{display:inline-flex;align-items:center;gap:6px;color:var(--muted);
  text-decoration:none;font-weight:500;font-size:13px}
 .backlink:hover{color:var(--text)}
 .backlink svg{color:var(--faint)}
 code{background:var(--surface-2);border:1px solid var(--border);padding:1px 6px;
  border-radius:6px;font-size:12.5px}
 .trust{display:flex;align-items:center;gap:9px;justify-content:center;margin:16px auto 0;
  max-width:560px;padding:10px 14px;border:1px solid var(--border);border-radius:var(--r);
  background:var(--surface);color:var(--muted);font-size:13px}
 .trust svg{color:var(--green)}
 .trust b{color:var(--text);font-weight:600}
"""


def _theme_js():
    """סקריפט מעבר בהיר/כהה משותף — מחליף אייקון (שמש/ירח) + תווית בכפתור #themebtn."""
    moon = _json.dumps(icon("moon", 16) + "<span>מצב כהה</span>")
    sun = _json.dumps(icon("sun", 16) + "<span>מצב בהיר</span>")
    return (
        "<script>(function(){var MOON=" + moon + ",SUN=" + sun + ";"
        "window.toggleTheme=function(){var r=document.documentElement,"
        "cur=r.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');"
        "var nx=cur==='dark'?'light':'dark';r.setAttribute('data-theme',nx);"
        "try{localStorage.setItem('fl-theme',nx);}catch(e){}updateThemeBtn();};"
        "window.updateThemeBtn=function(){var b=document.getElementById('themebtn');if(!b)return;"
        "var cur=document.documentElement.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');"
        "b.innerHTML=(cur==='dark'?SUN:MOON);};updateThemeBtn();})();</script>"
    )


THEME_JS = _theme_js()


@app.context_processor
def _inject_design_system():
    """מזריק את מערכת העיצוב (CSS/אייקונים/JS) לכל התבניות אוטומטית."""
    return {"theme_css": THEME_CSS, "icon": icon, "theme_js": THEME_JS,
            "theme_head": THEME_HEAD}


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


def _hebrew_headers(mapping):
    """מיפוי {target: כותרת בעברית} לייצוא לאקסל. אם אין שם עברי בקטלוג —
    נשאר קוד השדה. כשיש כפילות בשם, מוסיפים את הקוד בסוגריים."""
    cols = core.all_columns(mapping)
    titles = [(c["target"], (c.get("title") or "").strip()) for c in cols]
    seen = {}
    for _t, name in titles:
        if name:
            seen[name] = seen.get(name, 0) + 1
    out = {}
    for target, name in titles:
        if not name:
            out[target] = target
        elif seen.get(name, 0) > 1:
            out[target] = f"{name} ({target})"
        else:
            out[target] = name
    return out


def _rejected_df(mapping, items):
    """items: רשימת (excel_row, {target:value}, reason). הכותרות בעברית."""
    targets = [c["target"] for c in core.all_columns(mapping)]
    heb = _hebrew_headers(mapping)
    data = []
    for excel_row, values, reason in items:
        row = dict(values)
        row["__excel_row__"] = excel_row
        row["__reason__"] = reason
        data.append(row)
    df = pd.DataFrame(data, columns=targets + ["__excel_row__", "__reason__"])
    heb["__excel_row__"] = "שורה באקסל"      # שם ייחודי — 'שורה' תפוס ע\"י LINE
    heb["__reason__"] = "סיבת פסילה"
    return df.rename(columns=heb)


# ---------------------------------------------------------------------------
# עמוד ההעלאה
# ---------------------------------------------------------------------------
UPLOAD = """
<!doctype html><html lang="he" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>הכנת קובץ טעינה — Priority ERP</title>
{{ theme_head|safe }}
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Assistant:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
{{ theme_css|safe }}
 .wrap{max-width:660px;margin:0 auto;padding:52px 20px 60px}
 .hero{text-align:center;margin-bottom:28px}
 .hero .logo{width:52px;height:52px;border-radius:14px;margin:0 auto 18px;display:grid;place-items:center;
  color:var(--accent);background:var(--accent-soft);border:1px solid var(--accent-border)}
 h1{font-size:27px;font-weight:700;margin:0 0 8px;letter-spacing:-.03em}
 .hero p{color:var(--muted);margin:0;font-size:15.5px;max-width:460px;margin:0 auto}
 .card{padding:24px}
 .row{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:6px}.row>div{flex:1;min-width:170px;margin-bottom:16px}
 .drop{border:1.5px dashed var(--border-strong);border-radius:var(--r);padding:32px 20px;text-align:center;
  cursor:pointer;background:var(--surface-2);transition:border-color .15s,background .15s}
 .drop:hover{border-color:var(--accent)}
 .drop.over{border-color:var(--accent);background:var(--accent-soft)}
 .drop .ico{color:var(--faint);display:block;margin:0 auto 10px;width:fit-content}
 .drop b{color:var(--accent);font-weight:600}.drop .fmts{display:block;color:var(--faint);margin-top:8px;font-size:12.5px;letter-spacing:.02em}
 .fname{margin-top:12px;font-weight:600;color:var(--green);display:inline-flex;align-items:center;gap:6px}
 .err{background:var(--red-soft);border:1px solid var(--red);color:var(--red);border-radius:var(--r);padding:15px 17px;white-space:pre-wrap}
 form.card{margin-top:2px}
</style></head><body>
 <header class="topbar">
  {{ brand|safe }}
  <nav class="topnav">
   <a class="navbtn" href="/rates">{{ icon('rates',16)|safe }}<span>שערי בנק ישראל</span></a>
   <a class="navbtn" href="/history">{{ icon('history',16)|safe }}<span>היסטוריה</span></a>
   {% if auth_on %}<a class="navbtn" href="/logout">{{ icon('logout',16)|safe }}<span>יציאה</span></a>{% endif %}
   <button id="themebtn" class="navbtn" onclick="toggleTheme()" title="החלף מצב תצוגה" aria-label="החלף מצב תצוגה"></button>
  </nav>
 </header>
 <div class="wrap">
 <div class="hero">
  <div class="logo">{{ icon('upload',26)|safe }}</div>
  <h1>הכנת קובץ טעינה ל-Priority ERP</h1>
  <p>העלה קובץ אקסל, בחר מסך יעד, וקבל טבלת טעינה חכמה לפני הפקת הקובץ.</p>
 </div>
 {% if error %}
  <div class="card" style="padding:22px"><div class="err">{{ error }}</div>
   <p style="margin:14px 0 0"><a class="backlink" href="/">{{ icon('arrow-r',15)|safe }} חזרה</a></p></div>
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
   <div class="drop" id="drop"><span class="ico">{{ icon('file',28)|safe }}</span>
    <b>גרור לכאן קובץ</b> או לחץ לבחירה<span class="fmts">xlsx · txt · dat · csv</span>
    <input type="file" id="file" name="file" accept=".xlsx,.xls,.txt,.dat,.csv,.tsv" hidden required>
    <div class="fname" id="fname"></div></div>
   <button type="submit" class="btn btn-primary btn-lg" style="margin-top:18px">
    טען לטבלה {{ icon('arrow-l',17)|safe }}</button>{% endif %}
  </form>
  <div class="trust">{{ icon('lock',16)|safe }}
   <span><b>הכל רץ מקומית</b> — הקובץ לא נשלח לשום שרת חיצוני. הכלי מזהה אוטומטית את שורת הכותרת גם כשאינה בשורה הראשונה.</span></div>
 {% endif %}
 </div>
<script>
 const drop=document.getElementById('drop'),file=document.getElementById('file'),fname=document.getElementById('fname');
 const FICO='{{ icon("check",15)|safe }}';
 if(drop){drop.addEventListener('click',()=>file.click());
  file.addEventListener('change',()=>{if(file.files[0])fname.innerHTML=FICO+' '+file.files[0].name;});
  ['dragover','dragenter'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add('over');}));
  ['dragleave','drop'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove('over');}));
  drop.addEventListener('drop',ev=>{file.files=ev.dataTransfer.files;if(file.files[0])fname.innerHTML=FICO+' '+file.files[0].name;});}
</script>
{{ theme_js|safe }}
</body></html>
"""


# ---------------------------------------------------------------------------
# עמוד טבלת הטעינה
# ---------------------------------------------------------------------------
GRID = """
<!doctype html><html lang="he" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>טבלת טעינה — {{ screen }}</title>
{{ theme_head|safe }}
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Assistant:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
{{ theme_css|safe }}
 /* מיפוי טוקני הטבלה הישנים למערכת המשותפת (רקעי סטטוס לתאים) */
 :root{--brand:var(--accent);--brand-2:var(--accent);
  --bad-bg:var(--red-soft);--bad-fg:var(--red);--warn-bg:var(--amber-soft);--warn-fg:var(--amber);
  --ok-bg:var(--green-soft);--ok-fg:var(--green);--ign-bg:var(--accent-soft);--ign-fg:var(--accent);
  --tot-bg:var(--surface-3);--tot-fg:var(--muted)}
 .apphead .ttl h1{margin:0}.apphead .ttl .sub{margin:0}
 .wrap{max-width:1460px;margin:0 auto;padding:22px 18px 90px}
 h1{font-size:23px;font-weight:800;margin:0 0 3px;letter-spacing:-.01em}
 .sub{color:var(--muted);font-size:14px;margin:0 0 16px}
 .bar{display:flex;gap:9px;align-items:center;flex-wrap:wrap;padding:12px 14px;margin-bottom:14px;
  background:var(--surface);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow)}
 .pill{border-radius:999px;padding:6px 14px;font-weight:700;font-size:13.5px}
 .pill.tot{background:var(--tot-bg);color:var(--tot-fg)}.pill.ok{background:var(--ok-bg);color:var(--ok-fg)}
 .pill.bad{background:var(--bad-bg);color:var(--bad-fg)}.pill.warn{background:var(--warn-bg);color:var(--warn-fg)}
 .pill.ign{background:var(--ign-bg);color:var(--ign-fg)}
 button{border:0;border-radius:var(--r);padding:9px 14px;font-size:14px;font-weight:600;cursor:pointer;font-family:inherit;transition:background .13s,border-color .13s,transform .05s;display:inline-flex;align-items:center;gap:7px}
 button svg{flex:none}
 .b-check{background:var(--surface);color:var(--text);border:1px solid var(--border-strong)}.b-check:hover{background:var(--surface-2);border-color:var(--faint)}
 .b-check:disabled{opacity:.45;cursor:default;background:var(--surface)}.b-check:disabled:hover{border-color:var(--border-strong)}
 .b-gen{background:var(--green);color:#fff}
 .b-gen:hover{filter:brightness(.94)}
 .b-save{background:var(--accent);color:var(--accent-fg)}
 .b-save:hover{background:var(--accent-hover)}
 button:active{transform:translateY(.5px)}
 .spacer{flex:1}a.back{color:var(--muted);text-decoration:none;font-weight:500;font-size:13px;display:inline-flex;align-items:center;gap:6px}
 a.back:hover{color:var(--text)}
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
 .modal-bg{display:none;position:fixed;inset:0;background:rgba(15,23,42,.5);z-index:80;align-items:center;justify-content:center}
 .modal{background:var(--surface);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-lg);
  padding:24px;width:min(440px,92vw)}
 .modal h3{margin:0 0 8px;font-size:19px}.modal p{margin:0 0 16px;color:var(--muted);font-size:14px}
 .modal input{width:100%;padding:12px 13px;border:1.5px solid var(--border);border-radius:12px;font:inherit;font-size:15px;
  background:var(--surface-2);color:var(--text)}
 .modal input+.ml{margin-top:12px}
 .modal .ml{display:block;font-size:13px;font-weight:600;color:var(--muted);margin:0 0 6px 2px}
 .modal input:focus{outline:none;border-color:var(--brand);box-shadow:0 0 0 4px rgba(99,102,241,.15);background:var(--surface)}
 .modal-btns{display:flex;gap:10px;margin-top:18px}.modal-btns button{width:auto}
 .toast.ok{border-left-color:#16a34a}.toast.err{border-left-color:var(--red)}
 .pager{display:flex;gap:10px;align-items:center;justify-content:center;margin:16px 0;font-size:14px;color:var(--muted)}
 .pager button{background:var(--surface);color:var(--text);border:1px solid var(--border)}.pager button:disabled{opacity:.4;cursor:default}
 .dl{display:inline-flex;align-items:center;gap:7px;color:#fff;text-decoration:none;border-radius:var(--r);padding:10px 18px;font-weight:600;font-size:14px;margin:6px 8px 6px 0;transition:filter .13s;background:var(--green)}
 .dl:hover{filter:brightness(.94)}
 .dl.rej{background:var(--red)}.dl.rep{background:var(--muted)}
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
 .jbar .jt{font-weight:700;color:var(--accent);align-self:center;margin-inline-end:4px;display:inline-flex;align-items:center;gap:7px}
 .b-jchk{background:var(--surface);color:var(--text);border:1px solid var(--border-strong)}.b-jchk:hover{background:var(--surface-2)}
 .b-jbal{background:var(--accent);color:var(--accent-fg)}.b-jbal:hover{background:var(--accent-hover)}
 .bar2{margin-top:-6px;padding:10px 14px}.tool-lbl{font-weight:700;color:var(--muted);font-size:14px}
 .bar2 .mini{padding:7px 10px;border:1.5px solid var(--border);border-radius:9px;background:var(--surface-2);color:var(--text);font-family:inherit;font-size:14px}
 .bar2 .mini#bulkval{min-width:200px}
 /* כפתור הסתרת עמודה בכותרת */
 th.col .hidecol{position:absolute;left:14px;top:3px;cursor:pointer;color:var(--muted);opacity:0;
  font-size:12px;line-height:1;padding:2px 4px;border-radius:5px;transition:.12s;z-index:5}
 th.col:hover .hidecol{opacity:.6}
 th.col .hidecol:hover{opacity:1;background:var(--red-soft);color:var(--red)}
 /* סרגל עמודות מוסתרות */
 #hiddenbar{display:none;align-items:center;gap:8px;flex-wrap:wrap;background:var(--surface);
  border:1px solid var(--border);border-radius:var(--r);padding:9px 14px;margin:8px 0}
 #hiddenbar .hb-lbl{font-size:13px;font-weight:600;color:var(--muted)}
 .hchip{display:inline-flex;align-items:center;gap:5px;background:var(--surface-2);
  border:1px solid var(--border-strong);border-radius:999px;padding:4px 11px;font-size:12.5px;
  cursor:pointer;transition:.12s}
 .hchip:hover{border-color:var(--accent);color:var(--accent)}
 .hchip b{font-size:14px;line-height:1}
 tr.filterrow th{padding:4px 6px;position:sticky;top:0}
 tr.filterrow input{width:100%;min-width:90px;padding:6px 8px;border:1px solid var(--border);border-radius:7px;background:var(--surface);color:var(--text);font:inherit;font-size:13px}
</style></head><body>
 <header class="topbar">
  <div style="display:flex;align-items:center;gap:12px;min-width:0">
   <a class="navbtn solid" href="/" title="חזרה לדף הבית">{{ icon('home',16)|safe }}<span>דף הבית</span></a>
   <h1 style="font-size:16px;font-weight:700;margin:0;letter-spacing:-.02em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">טבלת טעינה · {{ screen }}</h1>
  </div>
  <nav class="topnav">
   {{ brand|safe }}
   <button id="themebtn" class="navbtn" onclick="toggleTheme()" title="החלף מצב תצוגה" aria-label="החלף מצב תצוגה"></button>
  </nav>
 </header>
 <div class="wrap">
 <div class="bar">
  <span class="pill tot" id="p-tot">סה״כ 0</span>
  <span class="pill ok" id="p-ok">תקינות 0</span>
  <span class="pill bad" id="p-bad">שגויות 0</span>
  <span class="pill warn" id="p-warn">אזהרות 0</span>
  <span class="pill ign" id="p-ign">מיוצאות למרות בעיה 0</span>
  <span class="spacer"></span>
  <button class="b-check" id="undobtn" onclick="undo()" title="בטל את הפעולה האחרונה (Ctrl+Z)" disabled>{{ icon('undo',15)|safe }}<span>ביטול</span></button>
  <button class="b-check" onclick="clearFilters()" title="נקה את כל הסינונים בטבלה">{{ icon('filter-off',15)|safe }}<span>בטל סינון</span></button>
  <button class="b-check" id="toggleview" onclick="toggleView()">{{ icon('search',15)|safe }}<span>הצג רק שורות בעייתיות</span></button>
  <button class="b-check" onclick="ignoreAllWarnings()" title="סמן את כל שורות האזהרה כמיוצאות">{{ icon('check',15)|safe }}התעלם מאזהרות</button>
  <button class="b-check" onclick="revalidate()">{{ icon('check-list',15)|safe }}בדוק מחדש</button>
  <button class="b-gen" onclick="generate()">{{ icon('download',15)|safe }}צור קובץ טעינה</button>
  <button class="b-save" onclick="saveLoad()" title="שמור את הטעינה בהיסטוריה לאחזור עתידי">{{ icon('check-circle',15)|safe }}שמירה בהיסטוריה</button>
  <a class="back" href="/history">{{ icon('history',15)|safe }}היסטוריה</a>
 </div>
 <div class="bar bar2">
  <span class="tool-lbl">עדכון גורף</span>
  <select id="bulkcol" class="mini"></select>
  <input id="bulkval" class="mini" placeholder="ערך חדש לכל השורות">
  <button class="b-check" onclick="bulkUpdate()">החל על הכל</button>
 </div>
 <div id="banner"></div><div id="mapping"></div><div id="journalbar"></div>
 <div id="hiddenbar"></div><div id="toast" class="toast"></div>
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
 <div id="savemodal" class="modal-bg" onclick="if(event.target===this)closeSaveModal()">
  <div class="modal">
   <h3>💾 שמירה בהיסטוריה</h3>
   <p>תן מזהה/שם ולקוח לטעינה — כך תזהה אותה במסך ההיסטוריה. שמירה חוזרת של אותו מזהה+לקוח תישמר כ<b>גרסה חדשה</b> באותו קובץ (לוג שינויים).</p>
   <label class="ml">מזהה/שם הטעינה</label>
   <input id="savename" placeholder="למשל: יומן ינואר 2026" onkeydown="if(event.key==='Enter'){focusClient()}if(event.key==='Escape')closeSaveModal()">
   <label class="ml">לקוח</label>
   <input id="saveclient" placeholder="שם/מזהה לקוח" onkeydown="if(event.key==='Enter')doSave();if(event.key==='Escape')closeSaveModal()">
   <div class="modal-btns">
    <button class="b-save" onclick="doSave()">💾 שמור</button>
    <button class="b-check" onclick="closeSaveModal()">ביטול</button>
   </div>
  </div>
 </div>
<script>
const GRID = {{ grid|tojson }};
const PAGE_SIZE = 100;
let page = 0;
let colOrder = GRID.columns.map((_, i) => i);   // סדר תצוגה/ייצוא של העמודות
let colWidths = {};                             // רוחב מותאם לעמודה (ci -> px)
let colFilter = {};                             // סינון לכל עמודה (ci -> טקסט)
let hiddenCols = new Set();                     // עמודות שהוסתרו (לא מוצגות ולא מיוצאות)
// סדר העמודות המוצגות בפועל (ללא המוסתרות) — משמש לתצוגה וגם לייצוא
function visCols(){ return colOrder.filter(ci => !hiddenCols.has(ci)); }
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
  const changes=[];
  GRID.rows.forEach((r,idx)=>{ if(r.cells[ci] && r.cells[ci].value!==val){ changes.push({gi:idx,prev:r.cells[ci].value}); r.cells[ci].value=val; } });
  if(changes.length) pushUndo({type:'bulk',ci,changes,label:'עדכון גורף «'+(GRID.columns[ci].title||GRID.columns[ci].target)+'» ('+changes.length+' שורות)'});
  render(); flash('ok','עודכנו '+changes.length+' שורות בעמודה '+GRID.columns[ci].target+'.');
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
  b.innerHTML = (GRID.mode==='errors' || onlyProblems)
    ? '{{ icon("check-list",15)|safe }}<span>הצג את כל השורות</span>'
    : '{{ icon("search",15)|safe }}<span>הצג רק שורות בעייתיות</span>';
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
    for(const ci of visCols()){
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
         ' onfocus="cellFocus('+gi+','+ci+',this.value)"'+
         ' oninput="upd('+gi+','+ci+',this.value)"'+
         ' onchange="cellChange('+gi+','+ci+',this.value)">'+fd+'</td>';
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
  for(const ci of visCols()){ const c=cols[ci];
    const w=colWidths[ci]?' style="min-width:'+colWidths[ci]+'px"':'';
    h+='<th class="col" draggable="true" data-ci="'+ci+'"'+w+' ondragstart="dragStart(event,'+ci+
       ')" ondragover="dragOver(event)" ondragleave="dragLeave(event)" ondrop="dropCol(event,'+ci+
       ')" ondragend="dragEnd(event)"><span class="rez" title="גרור לשינוי רוחב" onmousedown="startResize(event,'+ci+
       ')"></span><span class="hidecol" title="הסתר עמודה זו (לא תיוצא)" draggable="false"'+
       ' onclick="event.stopPropagation();hideCol('+ci+')">✕</span>'+
       '<span class="grip">⋮⋮</span><span class="tgt">'+esc(c.title||c.target)+
       (c.required?' <span class="reqdot" title="שדה חובה">•</span>':'')+
       '</span><span class="src">'+(c.title?esc(c.target):(c.constant?'ערך קבוע':esc(c.source||'')))+'</span></th>';
  }
  h+='</tr>';
  h+='<tr class="filterrow"><th class="act"></th><th class="rownum">🔎</th>';   // סינון קבוע לכל עמודה
  for(const ci of visCols())
    h+='<th><input value="'+esc(colFilter[ci]||'')+'" placeholder="סנן" oninput="setFilter('+ci+',this.value)"></th>';
  h+='</tr></thead><tbody id="gridbody">'+buildRows(slice,cols)+'</tbody>';
  $('grid').innerHTML=h;
  renderPager(disp.length,pages);
  updateCounts();
  renderHiddenBar();
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

// ===== ביטול פעולה אחרונה (UNDO) =====
// מחסנית פעולות הפיכות: עריכת תא, מילוי-עמודה, ועדכון גורף. כל פעולה שומרת את
// הערכים הקודמים כדי שנוכל לשחזר אותם. Ctrl+Z מפעיל אף הוא.
let UNDO=[]; const UNDO_MAX=200; let _cellPrev=null;
function pushUndo(entry){ UNDO.push(entry); if(UNDO.length>UNDO_MAX) UNDO.shift(); updateUndoBtn(); }
function updateUndoBtn(){ const b=$('undobtn'); if(b) b.disabled = UNDO.length===0; }
function cellFocus(gi,ci,v){ _cellPrev=v; }              // ערך התא לפני העריכה
function cellChange(gi,ci,v){                            // בעת יציאה מהתא — רושמים לביטול
  if(_cellPrev!==null && _cellPrev!==v)
    pushUndo({type:'cell',ci,changes:[{gi:gi,prev:_cellPrev}],label:'עריכת תא'});
  _cellPrev=null;
}
async function undo(){
  const e=UNDO.pop();
  if(!e){ flash('err','אין פעולה לביטול.'); return; }
  (e.changes||[]).forEach(ch=>{
    const r=GRID.rows[ch.gi];
    if(r && r.cells[e.ci]) r.cells[e.ci].value=ch.prev;
  });
  updateUndoBtn();
  render();                                             // עדכון מיידי של הטבלה מהמודל
  await revalidate();                                   // רענון צביעה/סטטוסים מהשרת
  flash('ok','בוטל: '+(e.label||'הפעולה האחרונה')+'.');
}
// מילוי ערך תא לכל שאר השורות של אותה עמודה (כמו גרירה באקסל).
// כשיש סינון פעיל — ממלא רק את השורות המסוננות/המוצגות.
async function fillDown(gi,ci){
  const src=GRID.rows[gi] && GRID.rows[gi].cells[ci];
  if(!src) return;
  const val=src.value; let n=0; const changes=[];
  const visible=new Set(displayed().map(x=>x[0]));   // אינדקסים של השורות המוצגות
  GRID.rows.forEach((r,idx)=>{ if(visible.has(idx) && r.cells[ci] && r.cells[ci].value!==val){ changes.push({gi:idx,prev:r.cells[ci].value}); r.cells[ci].value=val; n++; } });
  const nm=GRID.columns[ci].title||GRID.columns[ci].target;
  if(changes.length) pushUndo({type:'fill',ci,changes,label:'מילוי עמודה «'+nm+'» ('+n+' שורות)'});
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

// --- הסתרת עמודות (לא מוצגות בטבלה ולא נכתבות לקובץ/לאקסל) ---
function colName(ci){ const c=GRID.columns[ci]; return c ? (c.title||c.target) : ''; }
function hideCol(ci){
  const c=GRID.columns[ci];
  if(c && c.required){ flash('err','לא ניתן להסתיר שדה חובה («'+esc(colName(ci))+'»).'); return; }
  if(visCols().length<=1){ flash('err','חייבת להישאר לפחות עמודה אחת מוצגת.'); return; }
  hiddenCols.add(ci); delete colFilter[ci]; page=0; render();
  flash('ok','העמודה «'+esc(colName(ci))+'» הוסתרה — לא תיכלל בייצוא.');
}
function showCol(ci){ hiddenCols.delete(ci); render(); }
function showAllCols(){ if(!hiddenCols.size) return; hiddenCols.clear(); render();
  flash('ok','כל העמודות המוסתרות הוחזרו.'); }
function renderHiddenBar(){
  const box=$('hiddenbar'); if(!box) return;
  if(!hiddenCols.size){ box.style.display='none'; box.innerHTML=''; return; }
  box.style.display='flex';
  let h='<span class="hb-lbl">עמודות מוסתרות ('+hiddenCols.size+'):</span>';
  colOrder.filter(ci=>hiddenCols.has(ci)).forEach(ci=>{
    h+='<span class="hchip" title="לחץ להצגה מחדש" onclick="showCol('+ci+')">'+
       esc(colName(ci))+' <b>+</b></span>';
  });
  h+='<button class="b-check" style="margin-inline-start:auto" onclick="showAllCols()">הצג את כל העמודות</button>';
  box.innerHTML=h;
}

// --- ביטול כל הסינונים בטבלה ---
function clearFilters(){
  const had=Object.keys(colFilter).length;
  colFilter={}; page=0; render();
  flash(had?'ok':'err', had? ('בוטלו '+had+' סינונים.') : 'אין סינונים פעילים.');
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
  if(!GRID.journal){ box.innerHTML=''; box.className=''; return; }
  box.className='jbar';
  box.innerHTML=
   '<span class="jt">{{ icon("balance",17)|safe }} תנועות יומן</span>'+
   '<div class="fld"><label>מטבע ראשי</label><input id="j-primary" value="ILS"></div>'+
   '<div class="fld"><label>מטבע משני</label><input id="j-secondary" value="USD"></div>'+
   '<div class="fld"><label>סף איזון ראשי</label><input id="j-maxp" type="number" step="0.01" value="1"></div>'+
   '<div class="fld"><label>סף איזון משני</label><input id="j-maxs" type="number" step="0.01" value="1"></div>'+
   '<button class="b-jchk" onclick="journalFx()">{{ icon("coins",15)|safe }}טיוב מט"ח</button>'+
   '<button class="b-jchk" onclick="journalCheck()">{{ icon("check-list",15)|safe }}בדיקת תנועות</button>'+
   '<button class="b-jbal" onclick="journalBalance()">{{ icon("balance",15)|safe }}איזון תנועות</button>';
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
    order:visCols().map(ci=>GRID.columns[ci].target),    // סדר עמודות לייצוא (ללא מוסתרות)
    hidden:[...hiddenCols].map(ci=>GRID.columns[ci] && GRID.columns[ci].target).filter(Boolean)};
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
// פתיחת חלון שמירה — המשתמש מזין מזהה/שם לטעינה
function saveLoad(){
  const inp=$('savename');
  if(!inp.value) inp.value=(GRID.source_name||'').replace(/\\.[^.]+$/,'');  // ברירת מחדל: שם הקובץ
  if(GRID.source_client && !$('saveclient').value) $('saveclient').value=GRID.source_client;
  $('savemodal').style.display='flex';
  setTimeout(()=>{inp.focus();inp.select();},40);
}
function focusClient(){ $('saveclient').focus(); $('saveclient').select(); }
function closeSaveModal(){ $('savemodal').style.display='none'; }
async function doSave(){
  const name=($('savename').value||'').trim();
  const client=($('saveclient').value||'').trim();
  if(!name){ $('savename').focus(); flash('err','יש להזין מזהה/שם לטעינה.'); return; }
  closeSaveModal();
  const body=collect(); body.name=name; body.client=client;
  const res=await post('/grid/save',body); if(!res)return;
  showDownloads(res,true);
  if(res.load_id)
    flash('ok','✓ נשמר בהיסטוריה: «'+esc(name)+'»'+(client?(' · '+esc(client)):'')+' ('+res.valid+' שורות).');
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

// קיצור מקלדת Ctrl+Z / Cmd+Z לביטול (כשלא עורכים באופן פעיל שדה טקסט חופשי)
document.addEventListener('keydown',function(ev){
  if((ev.ctrlKey||ev.metaKey) && !ev.shiftKey && (ev.key==='z'||ev.key==='Z')){
    const a=document.activeElement;
    // בתוך תא-טבלה: תן לדפדפן לבטל את הקלדת התו; אחרת — בטל פעולה שלמה
    if(a && a.tagName==='INPUT' && a.closest('#grid')) return;
    ev.preventDefault(); undo();
  }
});
updateToggleBtn(); updateUndoBtn();
fillBulkSelect(); renderBanner(); renderMapping(); renderJournal(); render();
</script>
{{ theme_js|safe }}
</body></html>
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
        "excel_columns": [c for c in df.columns if not str(c).startswith("__")],
        "assignment": assignment,
        "unmatched_required": req_missing, "unmatched_optional": opt_missing,
        "journal": mapping.get("journal"),  # תפקידי עמודות להסבת תנועות יומן
        "source_name": RUNS[run_id].get("source_name", ""),
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
    hidden = data.get("hidden") or []          # עמודות שהמשתמש הסתיר — לא ייצאו
    export_mapping = mapping
    if (order or hidden) and not mapping.get("leveled") and not core.subform_defs(mapping):
        valid_records, export_mapping = core.reorder_for_export(
            valid_records, mapping, order, hidden_targets=hidden)

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
        load_id = db.add_version({
            "screen": screen, "source": run.get("source_name", ""),
            "name": (data.get("name") or "").strip(),   # מזהה שהמשתמש הקליד בשמירה
            "client": (data.get("client") or "").strip(),   # לקוח שהמשתמש הקליד בשמירה
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
{{ theme_head|safe }}
<link href="https://fonts.googleapis.com/css2?family=Assistant:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
{{ theme_css|safe }}
 /* מיפוי שמות טוקנים ישנים למערכת המשותפת */
 :root{--brand:var(--accent);--brand-2:var(--accent);--ok-fg:var(--green);--bad-fg:var(--red)}
 .wrap{max-width:1180px;margin:0 auto;padding:24px 18px 70px}
 h1{font-size:20px;font-weight:700;margin:0;letter-spacing:-.02em;display:flex;align-items:center;gap:9px}
 h1 svg{color:var(--accent)}
 .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);box-shadow:var(--shadow);overflow:hidden}
 .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}
 .kpi{background:var(--surface);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow);padding:14px 16px}
 .kpi .n{font-size:26px;font-weight:800;line-height:1.1}.kpi .l{font-size:12.5px;color:var(--muted);margin-top:3px}
 @media(max-width:720px){.kpis{grid-template-columns:repeat(2,1fr)}}
 .toolbar{display:flex;gap:10px;align-items:center;margin-bottom:14px;flex-wrap:wrap}
 .toolbar input[type=search],.toolbar select{padding:9px 12px;border:1.5px solid var(--border);border-radius:10px;background:var(--surface-2);color:var(--text);font:inherit}
 .toolbar input[type=search]{min-width:230px}
 .tablewrap{overflow-x:auto}
 table{border-collapse:collapse;width:100%;font-size:14px}
 th,td{text-align:right;padding:11px 14px;border-bottom:1px solid var(--border);white-space:nowrap}
 th{background:var(--surface-2);font-weight:700;position:relative}
 th.sortable{cursor:pointer;user-select:none}th.sortable:hover{color:var(--brand)}
 th .ar{font-size:10px;opacity:.7;margin-right:3px}
 .ok{color:var(--ok-fg);font-weight:700}.bad{color:var(--bad-fg);font-weight:700}
 tr.grp{cursor:pointer}tr.grp:hover{background:var(--surface-2)}
 tr.grp.open{background:var(--surface-2)}
 tr.ver{background:color-mix(in srgb,var(--surface-2) 55%,transparent);font-size:13px}
 tr.ver td:first-child{padding-right:34px}
 .chev{display:inline-block;width:16px;color:var(--muted);transition:transform .15s}
 tr.grp.open .chev{transform:rotate(90deg)}
 .name{font-weight:700}.vcount{font-size:11px;color:var(--muted);background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:1px 8px;margin-right:6px}
 .client{color:var(--brand);font-weight:600}
 .dl{color:var(--brand);text-decoration:none;font-weight:600;margin-left:10px;white-space:nowrap}
 .dl.open{color:var(--accent-fg);background:var(--brand);padding:4px 10px;border-radius:8px;font-size:12.5px}
 .btn{background:var(--surface);border:1px solid var(--border);border-radius:8px;cursor:pointer;font:inherit;font-size:13px;padding:5px 9px;color:var(--text)}
 .btn:hover{border-color:var(--brand);color:var(--brand)}
 .btn.dng{color:var(--bad-fg)}.btn.dng:hover{background:rgba(220,38,38,.1);border-color:var(--bad-fg);color:var(--bad-fg)}
 .btn.pri{background:var(--brand);color:var(--accent-fg);border-color:var(--brand)}
 .stsel{border-radius:20px;border:1.5px solid var(--border);padding:4px 9px;font:inherit;font-size:12.5px;font-weight:700;cursor:pointer;background:var(--surface)}
 .st-draft{color:var(--muted)}.st-ready{color:var(--brand);border-color:var(--brand)}
 .st-loaded{color:var(--ok-fg);border-color:var(--ok-fg);background:rgba(5,150,105,.08)}
 .delta{font-size:12px}.dg{color:var(--ok-fg);font-weight:700}.dr{color:var(--bad-fg);font-weight:700}
 .empty{padding:40px;text-align:center;color:var(--muted)}
 .tag{font-size:12px;color:var(--muted)}
 .acts{display:flex;gap:6px;justify-content:flex-start}
 input[type=checkbox]{width:16px;height:16px;cursor:pointer;accent-color:var(--brand)}
 #bulkbar{display:none;align-items:center;gap:10px;background:var(--brand);color:var(--accent-fg);border-radius:var(--r);padding:9px 15px;margin-bottom:12px;font-weight:600}
 #bulkbar .btn{background:color-mix(in srgb,var(--accent-fg) 16%,transparent);color:var(--accent-fg);border-color:color-mix(in srgb,var(--accent-fg) 36%,transparent)}
 #bulkbar .btn:hover{background:color-mix(in srgb,var(--accent-fg) 28%,transparent);color:var(--accent-fg)}
</style></head><body>
 <header class="topbar">
  <h1>{{ icon('history',20)|safe }} היסטוריית טעינות</h1>
  <nav class="topnav">
   <a class="navbtn" href="/">{{ icon('arrow-r',16)|safe }}<span>חזרה</span></a>
   <button id="themebtn" class="navbtn" onclick="toggleTheme()" title="החלף מצב תצוגה" aria-label="החלף מצב תצוגה"></button>
  </nav>
 </header>
 <div class="wrap">
 {% if dbinfo %}
 <div style="margin-bottom:14px;font-size:13px;padding:11px 15px;border-radius:var(--r);
   border:1px solid var(--border);
   background:{{ 'var(--green-soft)' if (dbinfo.ok and (dbinfo.backend=='postgres' or not dbinfo.vercel)) else 'var(--red-soft)' }}">
  {% if dbinfo.backend=='postgres' and dbinfo.ok %}
   מסד נתונים: <b>Postgres</b> — מחובר ושומר לצמיתות ({{ dbinfo.count }} רשומות).
  {% elif dbinfo.backend=='postgres' and not dbinfo.ok %}
   מסד נתונים: <b>Postgres</b> מוגדר אך אין חיבור — {{ dbinfo.error }}
  {% elif dbinfo.vercel %}
   מסד נתונים: <b>SQLite זמני</b> (‎/tmp‎) — <b>ההיסטוריה לא תישמר ב-Vercel</b>.
   חבר מסד Postgres (Storage → Create Database) ועשה Redeploy. ראה VERCEL.md.
  {% else %}
   מסד נתונים: <b>SQLite</b> ({{ dbinfo.count }} רשומות).
  {% endif %}
 </div>
 {% endif %}

 <div class="kpis">
  <div class="kpi"><div class="n">{{ stats.files }}</div><div class="l">קבצים בהיסטוריה</div></div>
  <div class="kpi"><div class="n">{{ stats.versions }}</div><div class="l">סה״כ גרסאות/טעינות</div></div>
  <div class="kpi"><div class="n">{{ '{:,}'.format(stats.valid_rows) }}</div><div class="l">שורות תקינות (גרסה אחרונה)</div></div>
  <div class="kpi"><div class="n">{{ stats.success }}%</div><div class="l">📈 אחוז הצלחה ממוצע</div></div>
 </div>

 <div id="bulkbar">
  <span>נבחרו <b id="bulkn">0</b> קבצים</span>
  <button class="btn" onclick="bulkDelete()">🗑 מחק נבחרים</button>
  <button class="btn" onclick="clearSel()">בטל בחירה</button>
 </div>

 <div class="card">
  <div style="padding:14px 16px 0">
   <div class="toolbar">
    <input type="search" id="q" placeholder="🔎 חיפוש לפי שם / לקוח / קובץ / מסך…" oninput="render()">
    <select id="fscreen" onchange="reloadScreen()">
     <option value="">— כל המסכים —</option>
     {% for s in screens %}<option value="{{ s }}" {% if s==sel_screen %}selected{% endif %}>{{ s }}</option>{% endfor %}
    </select>
    <select id="fstatus" onchange="render()">
     <option value="">— כל הסטטוסים —</option>
     <option value="draft">טיוטה</option>
     <option value="ready">מוכן</option>
     <option value="loaded">נטען לפריוריטי</option>
    </select>
    <span class="tag" id="cnt"></span>
   </div>
  </div>
  <div class="tablewrap">
   <table>
    <thead><tr>
     <th style="width:34px"><input type="checkbox" id="chkall" onclick="toggleAll(this)" title="בחר הכל"></th>
     <th class="sortable" data-k="name" onclick="setSort('name')">מזהה/שם <span class="ar"></span></th>
     <th class="sortable" data-k="client" onclick="setSort('client')">לקוח <span class="ar"></span></th>
     <th>מסך</th>
     <th class="sortable" data-k="ts" onclick="setSort('ts')">עודכן <span class="ar"></span></th>
     <th class="sortable" data-k="valid" onclick="setSort('valid')">תקינות <span class="ar"></span></th>
     <th>נפסלו</th>
     <th class="sortable" data-k="versions" onclick="setSort('versions')">גרסאות <span class="ar"></span></th>
     <th>סטטוס</th>
     <th>פעולות</th>
    </tr></thead>
    <tbody id="tb"></tbody>
   </table>
  </div>
 </div>
</div>

<script>const GROUPS={{ groups|tojson }};</script>
<script>
const $=id=>document.getElementById(id);
const ST={draft:{l:'טיוטה',c:'st-draft'},ready:{l:'מוכן',c:'st-ready'},loaded:{l:'נטען',c:'st-loaded'}};
const norm=s=>String(s==null?'':s);
let sortK='ts',sortDir=-1;                 // ברירת מחדל: עודכן לאחרונה, יורד
const expanded=new Set(),selected=new Set();
function esc(s){return norm(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function stKey(g){return g.status||'draft';}

function reloadScreen(){const s=$('fscreen').value;location.href='/history'+(s?('?screen='+encodeURIComponent(s)):'');}
function setSort(k){if(sortK===k)sortDir*=-1;else{sortK=k;sortDir=(k==='ts'||k==='valid'||k==='versions')?-1:1;}render();}
function toggleExp(k){if(expanded.has(k))expanded.delete(k);else expanded.add(k);render();}

function filtered(){
  const q=norm($('q').value).trim().toLowerCase(), fs=$('fstatus').value;
  let a=GROUPS.filter(g=>{
    if(fs && stKey(g)!==fs)return false;
    if(!q)return true;
    return [g.name,g.client,g.screen,(g.versions[0]||{}).__src].concat(
      g.versions.map(v=>v.__src)).some(x=>norm(x).toLowerCase().includes(q));
  });
  const val=g=>{const h=g.versions[0]||{};
    if(sortK==='name')return norm(g.name).toLowerCase();
    if(sortK==='client')return norm(g.client).toLowerCase();
    if(sortK==='ts')return norm(h.ts);
    if(sortK==='valid')return h.valid||0;
    if(sortK==='versions')return g.version_count||0;
    return '';};
  a.sort((x,y)=>{const vx=val(x),vy=val(y);return (vx<vy?-1:vx>vy?1:0)*sortDir;});
  return a;
}
function fmtDelta(d){
  if(!d)return '<span class="tag">— גרסה ראשונה —</span>';
  const p=[];
  if(d.valid)p.push('<span class="'+(d.valid>0?'dg':'dr')+'">'+(d.valid>0?'▲':'▼')+Math.abs(d.valid)+' תקינות</span>');
  if(d.invalid)p.push('<span class="'+(d.invalid>0?'dr':'dg')+'">'+(d.invalid>0?'▲':'▼')+Math.abs(d.invalid)+' נפסלות</span>');
  if(d.warnings)p.push('<span class="'+(d.warnings>0?'dr':'dg')+'">'+(d.warnings>0?'▲':'▼')+Math.abs(d.warnings)+' אזהרות</span>');
  return p.length?('<span class="delta">'+p.join(' · ')+'</span>'):'<span class="tag">אין שינוי בכמויות</span>';
}
function verFiles(v){
  let h='';
  if(v.has_snapshot)h+='<a class="dl open" href="/history/open/'+v.id+'">↗ פתח טבלה</a>';
  (v.files||[]).forEach(f=>{h+='<a class="dl" href="/history/file/'+f.id+'">⬇ '+esc(f.label)+'</a>';});
  return h||'<span class="tag">—</span>';
}
function stSelect(g){
  const k=stKey(g);let o='';
  for(const key in ST)o+='<option value="'+key+'"'+(key===k?' selected':'')+'>'+ST[key].l+'</option>';
  return '<select class="stsel '+ST[k].c+'" onchange="setStatus(this,\\''+g.key+'\\')" onclick="event.stopPropagation()">'+o+'</select>';
}

function render(){
  const list=filtered();
  $('cnt').textContent=list.length+' קבצים · '+list.reduce((s,g)=>s+g.version_count,0)+' גרסאות';
  if(!list.length){$('tb').innerHTML='<tr><td colspan="10"><div class="empty">לא נמצאו טעינות תואמות.</div></td></tr>';syncBulk();return;}
  let html='';
  for(const g of list){
    const h=g.versions[0]||{},op=expanded.has(g.key),sel=selected.has(g.key);
    html+='<tr class="grp'+(op?' open':'')+'" onclick="toggleExp(\\''+g.key+'\\')">'+
      '<td onclick="event.stopPropagation()"><input type="checkbox" '+(sel?'checked':'')+' onclick="toggleSel(\\''+g.key+'\\',this)"></td>'+
      '<td class="name"><span class="chev">▸</span>'+esc(g.name||'ללא שם')+
        (g.version_count>1?'<span class="vcount">v'+g.version_count+'</span>':'')+'</td>'+
      '<td>'+(g.client?'<span class="client">'+esc(g.client)+'</span>':'<span class="tag">—</span>')+'</td>'+
      '<td>'+esc(g.screen)+'</td>'+
      '<td class="tag">'+esc(h.ts)+'</td>'+
      '<td class="ok">'+(h.valid||0)+'</td>'+
      '<td class="'+(h.invalid?'bad':'')+'">'+(h.invalid||0)+'</td>'+
      '<td>'+g.version_count+'</td>'+
      '<td onclick="event.stopPropagation()">'+stSelect(g)+'</td>'+
      '<td onclick="event.stopPropagation()"><div class="acts">'+
        '<button class="btn" title="שנה שם/לקוח" onclick="renameGrp(\\''+g.key+'\\')">✏️</button>'+
        '<button class="btn dng" title="מחק קובץ (כל הגרסאות)" onclick="delGroup(\\''+g.key+'\\')">🗑</button>'+
      '</div></td></tr>';
    if(op){
      g.versions.forEach((v,i)=>{
        const num=g.version_count-i;
        html+='<tr class="ver">'+
          '<td></td>'+
          '<td><b>גרסה '+num+'</b>'+(i===0?' <span class="tag">(אחרונה)</span>':'')+'</td>'+
          '<td class="tag" colspan="2">'+esc(v.ts)+(v.user?(' · '+esc(v.user)):'')+(v.via==='cli'?' · CLI':'')+
             (v.__src?('<br>📄 '+esc(v.__src)):'')+'</td>'+
          '<td class="tag">'+esc(v.ts.split(' ')[1]||'')+'</td>'+
          '<td class="ok">'+(v.valid||0)+'</td>'+
          '<td class="'+(v.invalid?'bad':'')+'">'+(v.invalid||0)+'</td>'+
          '<td colspan="1">'+fmtDelta(v.delta)+'</td>'+
          '<td>'+verFiles(v)+'</td>'+
          '<td><button class="btn dng" title="מחק גרסה זו בלבד" onclick="delVer('+v.id+')">🗑 גרסה</button></td>'+
          '</tr>';
      });
    }
  }
  $('tb').innerHTML=html;
  syncBulk();
}

// --- בחירה מרובה ---
function toggleSel(k,el){if(el.checked)selected.add(k);else selected.delete(k);syncBulk();}
function toggleAll(el){selected.clear();if(el.checked)filtered().forEach(g=>selected.add(g.key));render();}
function clearSel(){selected.clear();$('chkall').checked=false;render();}
function syncBulk(){$('bulkn').textContent=selected.size;$('bulkbar').style.display=selected.size?'flex':'none';}

// --- פעולות (POST + רענון) ---
async function api(url,body){
  try{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
    const j=await r.json().catch(()=>({}));if(!r.ok||j.error){alert('שגיאה: '+(j.error||r.status));return false;}return true;
  }catch(e){alert('תקלה בתקשורת: '+e);return false;}
}
function grpById(k){return GROUPS.find(g=>g.key===k);}
async function setStatus(el,k){const g=grpById(k);if(!g)return;g.status=el.value;
  el.className='stsel '+ST[el.value].c;
  await api('/history/status',{screen:g.screen,name:g.name,client:g.client,status:el.value});}
async function renameGrp(k){const g=grpById(k);if(!g)return;
  const nm=prompt('מזהה/שם הטעינה:',g.name||'');if(nm===null)return;
  const cl=prompt('לקוח:',g.client||'');if(cl===null)return;
  if(await api('/history/rename',{screen:g.screen,name:g.name,client:g.client,new_name:nm.trim(),new_client:cl.trim()}))location.reload();}
async function delGroup(k){const g=grpById(k);if(!g)return;
  if(!confirm('למחוק את הקובץ «'+(g.name||g.screen)+'»'+(g.client?(' ('+g.client+')'):'')+' על כל '+g.version_count+' גרסאותיו?'))return;
  if(await api('/history/delete_group',{screen:g.screen,name:g.name,client:g.client}))location.reload();}
async function delVer(id){if(!confirm('למחוק גרסה זו בלבד?'))return;
  if(await api('/history/delete/'+id,{}))location.reload();}
async function bulkDelete(){if(!selected.size)return;
  if(!confirm('למחוק '+selected.size+' קבצים (כל גרסאותיהם)?'))return;
  for(const k of selected){const g=grpById(k);if(g)await api('/history/delete_group',{screen:g.screen,name:g.name,client:g.client});}
  location.reload();}

function updateArrows(){document.querySelectorAll('th.sortable').forEach(th=>{
  const a=th.querySelector('.ar');a.textContent=(th.dataset.k===sortK)?(sortDir<0?'▼':'▲'):'';});}
const _r=render;render=function(){_r();updateArrows();};
render();
</script>
{{ theme_js|safe }}
</body></html>
"""


def _slim_groups(groups):
    """מכין את קבוצות הגרסאות ל-JSON קליל לצד-הלקוח (בלי תוכן קבצים)."""
    def slim_ver(v):
        return {
            "id": v["id"], "ts": v.get("ts") or "", "user": v.get("user") or "",
            "via": v.get("via") or "", "__src": v.get("source") or "",
            "total": v.get("total") or 0, "valid": v.get("valid") or 0,
            "invalid": v.get("invalid") or 0, "warnings": v.get("warnings") or 0,
            "has_snapshot": bool(v.get("has_snapshot")),
            "has_rejected": bool(v.get("has_rejected")),
            "files": [{"id": f["id"], "label": f.get("label") or f.get("name") or "קובץ"}
                      for f in (v.get("files") or [])],
            "delta": v.get("delta"),
        }
    return [{
        "key": g["key"], "screen": g["screen"], "name": g["name"], "client": g["client"],
        "status": g.get("status") or "", "version_count": g["version_count"],
        "versions": [slim_ver(v) for v in g["versions"]],
    } for g in groups]


@app.route("/history")
def history():
    screen = (request.args.get("screen") or "").strip() or None
    return render_template_string(
        HISTORY, groups=_slim_groups(core.read_history(300, screen=screen)),
        stats=core.history_stats(screen=screen),
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
    """מחיקת גרסה בודדת. עונה JSON ל-fetch, או מפנה חזרה בגלישה רגילה."""
    ok = db.delete_load(load_id)
    if request.is_json or request.headers.get("X-Requested-With"):
        return jsonify(ok=ok)
    return redirect("/history")


@app.route("/history/delete_group", methods=["POST"])
def history_delete_group():
    """מחיקת קובץ שלם — כל גרסאותיו — לפי (מסך + מזהה + לקוח)."""
    d = request.get_json(silent=True) or {}
    ok = db.delete_group(d.get("screen"), d.get("name"), d.get("client"))
    return jsonify(ok=ok)


@app.route("/history/status", methods=["POST"])
def history_status():
    """עדכון סטטוס העבודה (טיוטה/מוכן/נטען) לכל גרסאות הקובץ."""
    d = request.get_json(silent=True) or {}
    status = (d.get("status") or "").strip()
    if status not in ("", "draft", "ready", "loaded"):
        return jsonify(error="סטטוס לא חוקי"), 400
    ok = db.set_status(d.get("screen"), d.get("name"), d.get("client"),
                       "" if status == "draft" else status)
    return jsonify(ok=ok)


@app.route("/history/rename", methods=["POST"])
def history_rename():
    """שינוי המזהה/הלקוח של כל גרסאות הקובץ."""
    d = request.get_json(silent=True) or {}
    ok = db.rename_group(d.get("screen"), d.get("name"), d.get("client"),
                         new_name=d.get("new_name"), new_client=d.get("new_client"))
    return jsonify(ok=ok)


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
{{ theme_head|safe }}
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Assistant:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
{{ theme_css|safe }}
 .wrap{max-width:900px;margin:0 auto;padding:28px 20px 70px}
 .hero{text-align:center;margin-bottom:24px}
 .hero .logo{width:50px;height:50px;border-radius:14px;margin:0 auto 14px;display:grid;place-items:center;
  color:var(--accent);background:var(--accent-soft);border:1px solid var(--accent-border)}
 h1{font-size:25px;font-weight:700;margin:0 0 6px;letter-spacing:-.03em}.hero p{color:var(--muted);margin:0;font-size:15px}
 .card{padding:22px;margin-bottom:18px}
 .row{display:flex;gap:14px;flex-wrap:wrap;align-items:flex-end}.row>div{flex:1;min-width:180px}
 .chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px}
 .chip{display:inline-flex;align-items:center;gap:7px;background:var(--accent-soft);border:1px solid var(--accent-border);
  border-radius:999px;padding:6px 13px;font-size:13px;font-weight:600;color:var(--accent);cursor:pointer;user-select:none;transition:.12s}
 .chip:hover{background:var(--accent-border)}
 .chip small{color:var(--muted);font-weight:500}.chip .x{opacity:.6}
 table{border-collapse:collapse;width:100%;font-size:14px}
 th,td{text-align:right;padding:11px 14px;border-bottom:1px solid var(--border);white-space:nowrap}
 th{background:var(--surface-2);font-weight:600;color:var(--muted);position:sticky;top:0;font-size:13px}
 td.rate{font-weight:700;font-variant-numeric:tabular-nums;font-size:15px}
 .ok{color:var(--green);font-weight:600}.bad{color:var(--red);font-weight:600}.warn{color:var(--amber);font-weight:600}
 .note{background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r);padding:12px 15px;color:var(--muted);font-size:12.5px;margin-top:12px}
 .spin{display:inline-block;width:14px;height:14px;border:2px solid color-mix(in srgb,var(--accent-fg) 45%,transparent);border-top-color:var(--accent-fg);border-radius:50%;animation:sp .7s linear infinite;vertical-align:-2px;margin-left:7px}
 @keyframes sp{to{transform:rotate(360deg)}}
 code{direction:ltr;display:inline-block}
 .empty{padding:34px;text-align:center;color:var(--muted)}
</style></head><body>
 <header class="topbar">{{ brand|safe }}
  <nav class="topnav">
   <a class="navbtn" href="/">{{ icon('arrow-r',16)|safe }}<span>חזרה לטעינה</span></a>
   <button id="themebtn" class="navbtn" onclick="toggleTheme()" title="החלף מצב תצוגה" aria-label="החלף מצב תצוגה"></button>
  </nav>
 </header>
 <div class="wrap">
 <div class="hero"><div class="logo">{{ icon('rates',24)|safe }}</div>
  <h1>שערי בנק ישראל</h1>
  <p>משיכה חיה מ-API של בנק ישראל (מול השקל) — לאימות שהנתונים נמשכים כראוי.</p></div>

 <div class="card">
  <div class="row">
   <div><label for="rdate">תאריך</label><input type="date" id="rdate"></div>
   <div style="flex:none"><button class="btn btn-primary" id="gobtn" onclick="fetchRates()">משוך שערים {{ icon('arrow-l',16)|safe }}</button></div>
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
   '<span class="chip" onclick="toggle(\\''+esc(c)+'\\')">'+esc(c)+
   (DESC[c]?' <small>'+esc(DESC[c])+'</small>':'')+' <span class="x">×</span></span>').join('');
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
 $('rdate').value=today();renderChips();
</script>
{{ theme_js|safe }}
</body></html>
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


CONFIG_ERROR = """
<!doctype html><html lang="he" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>נדרשת הגדרת אבטחה</title>
<style>
 body{margin:0;font-family:-apple-system,"Segoe UI",system-ui,Arial,sans-serif;background:#0b1120;color:#e8edf6;
  display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px}
 .box{max-width:560px;background:#111a2e;border:1px solid #233047;border-radius:18px;padding:32px 30px;
  box-shadow:0 24px 60px rgba(0,0,0,.55);line-height:1.6}
 h1{font-size:22px;margin:0 0 12px}.i{font-size:40px}
 code{background:#0f1728;border:1px solid #233047;border-radius:7px;padding:2px 7px;font-size:13.5px;color:#a5b4fc}
 ol{padding-right:20px;margin:14px 0}.muted{color:#93a1b8;font-size:13.5px;margin-top:14px}
</style></head><body><div class="box">
 <div class="i">🔒</div>
 <h1>הגישה חסומה — נדרשת הגדרת אבטחה</h1>
 <p>האפליקציה פרוסה בענן אך <b>לא הוגדרה סיסמה</b>, ולכן היא נחסמה כדי למנוע גישה
    לא-מורשית. כדי להפעיל אותה בבטחה, הגדר במשתני-הסביבה של הפריסה:</p>
 <ol>
  <li><code>APP_PASSWORD</code> — הסיסמה להתחברות (חובה).</li>
  <li><code>SECRET_KEY</code> — מחרוזת אקראית ארוכה לחתימת ה-session (מומלץ מאוד,
      כדי שההתחברות תישמר בין הרצות).</li>
  <li>אופציונלי: <code>APP_USERNAME</code> (ברירת מחדל <code>admin</code>).</li>
 </ol>
 <p>לאחר ההגדרה — בצע <b>Redeploy</b>.</p>
 <p class="muted">להרצה פתוחה מכוונת (ללא סיסמה) אפשר להגדיר <code>ALLOW_OPEN=1</code>,
    אך לא מומלץ בסביבה ציבורית.</p>
</div></body></html>
"""


LOGIN = """
<!doctype html><html lang="he" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>התחברות — Priority ERP</title>
{{ theme_head|safe }}
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Assistant:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
{{ theme_css|safe }}
 body{display:grid;place-items:center;padding:20px}
 .brand{justify-content:center;margin-bottom:22px}
 .card{padding:32px 30px;width:min(390px,94vw);box-shadow:var(--shadow-lg)}
 .logo{width:50px;height:50px;border-radius:14px;margin:0 auto 14px;display:grid;place-items:center;
  color:var(--accent);background:var(--accent-soft);border:1px solid var(--accent-border)}
 h1{font-size:21px;font-weight:700;margin:0 0 4px;text-align:center;letter-spacing:-.02em}
 .sub{color:var(--muted);text-align:center;margin:0 0 22px;font-size:14px}
 .card label{margin:14px 0 6px}
 .err{background:var(--red-soft);border:1px solid var(--red);color:var(--red);
  border-radius:var(--r);padding:10px 14px;font-size:13.5px;margin-top:16px;text-align:center}
</style></head><body>
 <form class="card" method="post" action="/login">
  {{ brand|safe }}
  <div class="logo">{{ icon('lock',24)|safe }}</div>
  <h1>התחברות למערכת</h1>
  <p class="sub">הכנת קבצי טעינה ל-Priority ERP</p>
  <input type="hidden" name="next" value="{{ next }}">
  <label for="username">שם משתמש</label>
  <input id="username" name="username" autocomplete="username" autofocus>
  <label for="password">סיסמה</label>
  <input id="password" name="password" type="password" autocomplete="current-password">
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  <button type="submit" class="btn btn-primary btn-lg" style="margin-top:22px">
   התחבר {{ icon('arrow-l',16)|safe }}</button>
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
