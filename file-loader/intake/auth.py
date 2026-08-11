# -*- coding: utf-8 -*-
"""
auth.py — התחברות והרשאות לממשק קליטת הספקים

הממשק חשוף לאינטרנט ומזין נתונים ישירות לפריוריטי, ולכן הגישה אליו סגורה
תמיד — אין "מצב פתוח". כללי האבטחה:

  • כל עמוד (חוץ ממסך ההתחברות) דורש משתמש מחובר.
  • סיסמאות נשמרות כגיבוב PBKDF2-SHA256 עם מלח לכל משתמש.
  • ניסיונות התחברות מוגבלים בקצב, וחשבון ננעל זמנית אחרי כשלונות חוזרים.
  • ה-session פג אחרי חוסר פעילות (30 דק') ובכל מקרה אחרי 12 שעות.
  • משתמש ראשון נוצר ממשתני הסביבה INTAKE_ADMIN_USER / INTAKE_ADMIN_PASSWORD.
    בהרצה מקומית בלבד אפשר גם ליצור אותו במסך הקמה חד-פעמי.
"""

import functools
import os

from flask import redirect, request, session, url_for

from . import security, store

IDLE_TIMEOUT = 30 * 60          # שניות ללא פעילות עד ניתוק
ABSOLUTE_TIMEOUT = 12 * 60 * 60  # אורך חיים מרבי של session

login_limiter = security.RateLimiter(limit=10, window_seconds=15 * 60)
LOCKOUT_AFTER = 5
LOCKOUT_MINUTES = 15


def hosted():
    """האם אנחנו רצים בפריסה ציבורית (Vercel / Render)."""
    return bool(os.environ.get("VERCEL") or os.environ.get("RENDER"))


def setup_allowed():
    """
    מסך ההקמה הראשוני נפתח רק כשאין עדיין משתמשים, ורק בהרצה מקומית —
    אחרת כל מי שיגיע ראשון לכתובת הציבורית היה יכול להפוך לעצמו למנהל.
    בפריסה בענן: INTAKE_ADMIN_USER + INTAKE_ADMIN_PASSWORD.
    """
    if store.count_users():
        return False
    if os.environ.get("INTAKE_ALLOW_SETUP", "").lower() in ("1", "true", "yes"):
        return True
    return not hosted()


def bootstrap_admin():
    """יוצר משתמש מנהל ממשתני הסביבה, אם אין עדיין משתמשים."""
    username = (os.environ.get("INTAKE_ADMIN_USER") or "").strip()
    password = os.environ.get("INTAKE_ADMIN_PASSWORD") or ""
    if not username or not password or store.count_users():
        return None
    return store.create_user(
        username=username, password=password,
        display_name=os.environ.get("INTAKE_ADMIN_NAME") or username,
        phone=os.environ.get("INTAKE_ADMIN_PHONE") or "",
        role="admin")


def needs_setup():
    """אין משתמשים כלל — הממשק עוד לא הוקם."""
    return store.count_users() == 0


# ---------------------------------------------------------------------------
# session
# ---------------------------------------------------------------------------
def _client_key():
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or request.remote_addr or "?"


def start_session(user):
    import time
    session["intake_uid"] = user["id"]
    session["intake_login_at"] = int(time.time())
    session["intake_seen_at"] = int(time.time())
    session.permanent = False


def end_session():
    for key in ("intake_uid", "intake_login_at", "intake_seen_at"):
        session.pop(key, None)


def current_user():
    """המשתמש המחובר, או None. מנתק אוטומטית session שפג או משתמש שהושבת."""
    import time
    user_id = session.get("intake_uid")
    if not user_id:
        return None

    now = int(time.time())
    if now - int(session.get("intake_login_at") or 0) > ABSOLUTE_TIMEOUT:
        end_session()
        return None
    if now - int(session.get("intake_seen_at") or 0) > IDLE_TIMEOUT:
        end_session()
        return None

    user = store.get_user_by_id(user_id)
    if not user or not user["active"]:
        end_session()
        return None

    session["intake_seen_at"] = now
    return user


def attempt_login(username, password):
    """
    מנסה להתחבר. מחזיר (user, error) — error הוא טקסט בעברית להצגה.
    ההודעה זהה לשם משתמש שגוי ולסיסמה שגויה, כדי לא לחשוף אילו שמות קיימים.
    """
    username = (username or "").strip().lower()
    key = f"{_client_key()}|{username}"
    allowed, wait = login_limiter.check(key)
    if not allowed:
        return None, f"יותר מדי ניסיונות התחברות. נסו שוב בעוד {wait} שניות."
    login_limiter.record(key)

    generic = "שם משתמש או סיסמה שגויים"
    user = store.get_user(username)
    if not user:
        security.verify_password(password, "")   # השהיה דומה, בלי לחשוף קיום
        return None, generic
    if not user["active"]:
        return None, "המשתמש חסום. פנו למנהל המערכת."
    if _locked(user):
        return None, f"החשבון נעול זמנית בעקבות ניסיונות שגויים. נסו בעוד {LOCKOUT_MINUTES} דקות."

    if not security.verify_password(password, user["password"]):
        failed = int(user["failed_count"] or 0) + 1
        changes = {"failed_count": failed}
        if failed >= LOCKOUT_AFTER:
            changes["locked_until"] = _lock_until()
            changes["failed_count"] = 0
        store.update_user(user["id"], **changes)
        return None, generic

    import datetime as _dt
    store.update_user(user["id"], failed_count=0, locked_until="",
                      last_login=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    login_limiter.reset(key)
    return store.get_user_by_id(user["id"]), None


def _lock_until():
    import datetime as _dt
    return (_dt.datetime.now() + _dt.timedelta(minutes=LOCKOUT_MINUTES)
            ).strftime("%Y-%m-%d %H:%M:%S")


def _locked(user):
    import datetime as _dt
    raw = user.get("locked_until") or ""
    if not raw:
        return False
    try:
        return _dt.datetime.now() < _dt.datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# עוטפים לנתיבים
# ---------------------------------------------------------------------------
def _unauthorized():
    """נתיבי JSON מקבלים 401; עמודים מופנים למסך ההתחברות."""
    from flask import jsonify
    if request.path.startswith("/intake/api/"):
        return jsonify(error="ההתחברות פגה — רעננו את העמוד והתחברו מחדש."), 401
    return redirect(url_for("intake.login", next=request.path))


def login_required(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return _unauthorized()
        return view(*args, user=user, **kwargs)
    return wrapper


def admin_required(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return _unauthorized()
        if user["role"] != "admin":
            from flask import jsonify
            if request.path.startswith("/intake/api/"):
                return jsonify(error="הפעולה מותרת למנהלי מערכת בלבד."), 403
            return redirect(url_for("intake.home"))
        return view(*args, user=user, **kwargs)
    return wrapper
