# -*- coding: utf-8 -*-
"""
store.py — שכבת הנתונים של ממשק קליטת הספקים

משתמש באותו מנוע מסד כמו שאר הכלי (`db.py`): Postgres כשמוגדר DATABASE_URL,
אחרת SQLite מקומי. ארבע טבלאות:

  intake_users        משתמשי הממשק (התחברות)
  intake_config       הגדרות — כולל פרטי החיבור לפריוריטי (סודות מוצפנים)
  intake_otp          קודי אימות שנשלחו (גיבוב בלבד, עם תפוגה)
  intake_submissions  יומן קליטה — מי טען, מתי, מה, ומה פריוריטי החזיר
"""

import datetime as _dt
import json

import db
from . import security

_ID = db._ID_COL
PH = db.PH


def _now():
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _rows(cur):
    """מחזיר רשומות כמילונים — עובד גם ב-SQLite (Row) וגם ב-Postgres (RealDict)."""
    return [dict(r) for r in cur.fetchall()]


def _row(cur):
    record = cur.fetchone()
    return dict(record) if record else None


_initialized = False


def init(force=False):
    """יוצר את הטבלאות (idempotent). רץ פעם אחת לכל תהליך, אלא אם כופים."""
    global _initialized
    if _initialized and not force:
        return
    _create_tables()
    _initialized = True


def _create_tables():
    with db._conn() as conn:
        cur = db._cursor(conn)
        cur.execute(
            "CREATE TABLE IF NOT EXISTS intake_users("
            f"  id {_ID},"
            "  username TEXT UNIQUE, password TEXT, display_name TEXT, phone TEXT,"
            "  role TEXT, active INTEGER, created_at TEXT, last_login TEXT,"
            "  failed_count INTEGER, locked_until TEXT)")
        cur.execute(
            "CREATE TABLE IF NOT EXISTS intake_config("
            "  k TEXT PRIMARY KEY, v TEXT, updated_at TEXT, updated_by TEXT)")
        cur.execute(
            "CREATE TABLE IF NOT EXISTS intake_otp("
            f"  id {_ID},"
            "  user_id INTEGER, phone TEXT, code_hash TEXT, salt TEXT,"
            "  payload_hash TEXT, channel TEXT, created_at TEXT, expires_at TEXT,"
            "  attempts INTEGER, verified_at TEXT, consumed_at TEXT)")
        cur.execute(
            "CREATE TABLE IF NOT EXISTS intake_submissions("
            f"  id {_ID},"
            "  ts TEXT, user_id INTEGER, username TEXT, screen TEXT,"
            "  key_value TEXT, supplier_name TEXT, phone TEXT, status TEXT,"
            "  message TEXT, payload TEXT, response TEXT, otp_id INTEGER)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_intake_otp_user ON intake_otp(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_intake_sub_ts ON intake_submissions(ts)")


# ---------------------------------------------------------------------------
# משתמשים
# ---------------------------------------------------------------------------
def count_users():
    with db._conn() as conn:
        cur = db._cursor(conn)
        cur.execute("SELECT COUNT(*) AS n FROM intake_users")
        return int(_row(cur)["n"])


def get_user(username):
    with db._conn() as conn:
        cur = db._cursor(conn)
        cur.execute(f"SELECT * FROM intake_users WHERE username={PH}", ((username or "").strip().lower(),))
        return _row(cur)


def get_user_by_id(user_id):
    with db._conn() as conn:
        cur = db._cursor(conn)
        cur.execute(f"SELECT * FROM intake_users WHERE id={PH}", (user_id,))
        return _row(cur)


def list_users():
    with db._conn() as conn:
        cur = db._cursor(conn)
        cur.execute("SELECT * FROM intake_users ORDER BY username")
        return _rows(cur)


def create_user(username, password, display_name="", phone="", role="user"):
    """יוצר משתמש. מחזיר את המזהה, או None אם שם המשתמש כבר תפוס."""
    username = (username or "").strip().lower()
    if not username:
        raise ValueError("שם משתמש ריק")
    if get_user(username):
        return None
    values = (username, security.hash_password(password), display_name.strip(),
              normalize_phone(phone), role, 1, _now(), "", 0, "")
    columns = ("username,password,display_name,phone,role,active,created_at,"
               "last_login,failed_count,locked_until")
    marks = ",".join([PH] * 10)
    with db._conn() as conn:
        cur = db._cursor(conn)
        if db.IS_PG:
            cur.execute(f"INSERT INTO intake_users({columns}) VALUES({marks}) RETURNING id", values)
            return _row(cur)["id"]
        cur.execute(f"INSERT INTO intake_users({columns}) VALUES({marks})", values)
        return cur.lastrowid


def update_user(user_id, **changes):
    """מעדכן שדות מותרים בלבד. `password` מגובב אוטומטית."""
    allowed = {"display_name", "phone", "role", "active", "password",
               "failed_count", "locked_until", "last_login"}
    sets, values = [], []
    for key, value in changes.items():
        if key not in allowed:
            continue
        if key == "password":
            value = security.hash_password(value)
        if key == "phone":
            value = normalize_phone(value)
        if key == "active":
            value = 1 if value else 0
        sets.append(f"{key}={PH}")
        values.append(value)
    if not sets:
        return
    values.append(user_id)
    with db._conn() as conn:
        cur = db._cursor(conn)
        cur.execute(f"UPDATE intake_users SET {','.join(sets)} WHERE id={PH}", values)


def delete_user(user_id):
    with db._conn() as conn:
        cur = db._cursor(conn)
        cur.execute(f"DELETE FROM intake_users WHERE id={PH}", (user_id,))


# ---------------------------------------------------------------------------
# הגדרות
# ---------------------------------------------------------------------------
# ערכי ברירת המחדל של ההגדרות. מפתחות שמסתיימים ב-`_secret` נשמרים מוצפנים.
DEFAULTS = {
    "priority_url": "",                  # שם החברה הוא חלק מהכתובת
    "priority_auth": "token",            # token / user / bearer
    "priority_token_secret": "",
    "priority_username": "",
    "priority_password_secret": "",
    "priority_verify_tls": "1",
    "otp_channel": "console",            # console / webhook / inforu / twilio
    "otp_phone_mode": "user",            # user = הטלפון של המשתמש בלבד; free = חופשי
    "otp_ttl_minutes": "5",
    "otp_sender_name": "",
    "otp_endpoint": "",
    "otp_secret": "",                    # מפתח/סיסמה של ספק הסמס
    "otp_user": "",
    "advanced_fields": "0",              # הצגת שלב "שדות נוספים"
    "duplicate_check": "1",              # בדיקת קיום מספר ספק לפני שליחה
}

_SECRET_SUFFIX = "_secret"

# ערכי פתיחה ממשתני סביבה — נוח לפריסה בענן, שבה עדיף לא להקליד סודות בטופס.
# ערך שנשמר במסך ההגדרות תמיד גובר על משתנה הסביבה.
ENV_FALLBACK = {
    "priority_url": "INTAKE_PRIORITY_URL",
    "priority_auth": "INTAKE_PRIORITY_AUTH",
    "priority_token_secret": "INTAKE_PRIORITY_TOKEN",
    "priority_username": "INTAKE_PRIORITY_USERNAME",
    "priority_password_secret": "INTAKE_PRIORITY_PASSWORD",
    "otp_channel": "INTAKE_OTP_CHANNEL",
    "otp_endpoint": "INTAKE_OTP_ENDPOINT",
    "otp_user": "INTAKE_OTP_USER",
    "otp_secret": "INTAKE_OTP_SECRET",
    "otp_sender_name": "INTAKE_OTP_SENDER",
}


def get_config():
    """כל ההגדרות, כשהסודות מפוענחים. ערכים חסרים מקבלים ברירת מחדל."""
    import os

    config = dict(DEFAULTS)
    for key, env_name in ENV_FALLBACK.items():
        value = os.environ.get(env_name)
        if value:
            config[key] = value.strip()

    with db._conn() as conn:
        cur = db._cursor(conn)
        cur.execute("SELECT k, v FROM intake_config")
        for row in _rows(cur):
            key, value = row["k"], row["v"]
            if key.endswith(_SECRET_SUFFIX):
                value = security.decrypt_secret(value)
            config[key] = value if value is not None else ""
    return config


def set_config(changes, updated_by=""):
    """שומר הגדרות. מפתח שאינו מוכר נדחה; סודות נשמרים מוצפנים."""
    now = _now()
    with db._conn() as conn:
        cur = db._cursor(conn)
        for key, value in changes.items():
            if key not in DEFAULTS:
                continue
            stored = security.encrypt_secret(value) if key.endswith(_SECRET_SUFFIX) else str(value)
            cur.execute(f"DELETE FROM intake_config WHERE k={PH}", (key,))
            cur.execute(
                f"INSERT INTO intake_config(k,v,updated_at,updated_by) VALUES({PH},{PH},{PH},{PH})",
                (key, stored, now, updated_by))


def config_is_ready(config=None):
    """האם הוגדרו פרטי חיבור מספיקים לפריוריטי."""
    config = config or get_config()
    if not config.get("priority_url"):
        return False
    if config.get("priority_auth") == "user":
        return bool(config.get("priority_username") and config.get("priority_password_secret"))
    return bool(config.get("priority_token_secret"))


# ---------------------------------------------------------------------------
# קודי אימות (OTP)
# ---------------------------------------------------------------------------
def create_otp(user_id, phone, code_hash, salt, payload_hash, channel, ttl_minutes):
    now = _dt.datetime.now()
    expires = now + _dt.timedelta(minutes=int(ttl_minutes))
    values = (user_id, normalize_phone(phone), code_hash, salt, payload_hash, channel,
              now.strftime("%Y-%m-%d %H:%M:%S"), expires.strftime("%Y-%m-%d %H:%M:%S"), 0, "", "")
    columns = ("user_id,phone,code_hash,salt,payload_hash,channel,created_at,"
               "expires_at,attempts,verified_at,consumed_at")
    marks = ",".join([PH] * 11)
    with db._conn() as conn:
        cur = db._cursor(conn)
        if db.IS_PG:
            cur.execute(f"INSERT INTO intake_otp({columns}) VALUES({marks}) RETURNING id", values)
            return _row(cur)["id"]
        cur.execute(f"INSERT INTO intake_otp({columns}) VALUES({marks})", values)
        return cur.lastrowid


def get_otp(otp_id):
    with db._conn() as conn:
        cur = db._cursor(conn)
        cur.execute(f"SELECT * FROM intake_otp WHERE id={PH}", (otp_id,))
        return _row(cur)


def bump_otp_attempts(otp_id):
    with db._conn() as conn:
        cur = db._cursor(conn)
        cur.execute(f"UPDATE intake_otp SET attempts=attempts+1 WHERE id={PH}", (otp_id,))


def mark_otp(otp_id, field):
    """מסמן `verified_at` או `consumed_at` בזמן הנוכחי."""
    if field not in ("verified_at", "consumed_at"):
        raise ValueError(field)
    with db._conn() as conn:
        cur = db._cursor(conn)
        cur.execute(f"UPDATE intake_otp SET {field}={PH} WHERE id={PH}", (_now(), otp_id))


def claim_otp(otp_id):
    """
    תופס את הקוד לשימוש בלעדי, באופן אטומי. מחזיר True רק למי שתפס אותו.
    נחוץ כי השרת מטפל בכמה בקשות במקביל: בלי התפיסה האטומית שתי לחיצות
    בו-זמנית על "טעינה" היו עוברות שתיהן את הבדיקה, ונוצרים שני ספקים.
    """
    with db._conn() as conn:
        cur = db._cursor(conn)
        cur.execute(
            f"UPDATE intake_otp SET consumed_at={PH} WHERE id={PH} AND "
            "(consumed_at IS NULL OR consumed_at='')", (_now(), otp_id))
        return cur.rowcount == 1


def release_otp(otp_id):
    """משחרר קוד שנתפס אך הטעינה נכשלה — כדי שלא יידרש אימות מחדש לחינם."""
    with db._conn() as conn:
        cur = db._cursor(conn)
        cur.execute(f"UPDATE intake_otp SET consumed_at='' WHERE id={PH}", (otp_id,))


def purge_old_otp(days=2):
    """מנקה קודים ישנים — אין סיבה לשמור אותם."""
    cutoff = (_dt.datetime.now() - _dt.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with db._conn() as conn:
        cur = db._cursor(conn)
        cur.execute(f"DELETE FROM intake_otp WHERE created_at < {PH}", (cutoff,))


# ---------------------------------------------------------------------------
# יומן הקליטה
# ---------------------------------------------------------------------------
def add_submission(entry):
    columns = ("ts,user_id,username,screen,key_value,supplier_name,phone,status,"
               "message,payload,response,otp_id")
    values = (entry.get("ts") or _now(), entry.get("user_id"), entry.get("username", ""),
              entry.get("screen", ""), entry.get("key_value", ""),
              entry.get("supplier_name", ""), entry.get("phone", ""),
              entry.get("status", ""), (entry.get("message") or "")[:2000],
              json.dumps(entry.get("payload") or {}, ensure_ascii=False),
              json.dumps(entry.get("response") or {}, ensure_ascii=False)[:8000],
              entry.get("otp_id"))
    marks = ",".join([PH] * 12)
    with db._conn() as conn:
        cur = db._cursor(conn)
        if db.IS_PG:
            cur.execute(f"INSERT INTO intake_submissions({columns}) VALUES({marks}) RETURNING id",
                        values)
            return _row(cur)["id"]
        cur.execute(f"INSERT INTO intake_submissions({columns}) VALUES({marks})", values)
        return cur.lastrowid


def list_submissions(limit=100, user_id=None):
    where, values = "", []
    if user_id is not None:
        where = f"WHERE user_id={PH}"
        values.append(user_id)
    values.append(int(limit))
    with db._conn() as conn:
        cur = db._cursor(conn)
        cur.execute(f"SELECT * FROM intake_submissions {where} "
                    f"ORDER BY id DESC LIMIT {PH}", values)
        return _rows(cur)


def get_submission(submission_id):
    with db._conn() as conn:
        cur = db._cursor(conn)
        cur.execute(f"SELECT * FROM intake_submissions WHERE id={PH}", (submission_id,))
        return _row(cur)


def submission_stats():
    with db._conn() as conn:
        cur = db._cursor(conn)
        cur.execute("SELECT status, COUNT(*) AS n FROM intake_submissions GROUP BY status")
        counts = {r["status"]: int(r["n"]) for r in _rows(cur)}
    return {
        "created": counts.get("created", 0),
        "failed": counts.get("failed", 0),
        "total": sum(counts.values()),
    }


# ---------------------------------------------------------------------------
# עזר
# ---------------------------------------------------------------------------
def normalize_phone(phone):
    """
    מנרמל מספר טלפון ישראלי לפורמט בינלאומי +972... — כך שאותו מספר
    שנכתב בכמה צורות ייחשב זהה, וספקי הסמס יקבלו מספר תקני.
    """
    raw = str(phone or "").strip()
    if not raw:
        return ""
    plus = raw.startswith("+")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
        plus = True
    if digits.startswith("972"):
        return "+" + digits
    if digits.startswith("0"):
        return "+972" + digits[1:]
    if plus:
        return "+" + digits
    return "+972" + digits
