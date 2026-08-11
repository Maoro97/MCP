# -*- coding: utf-8 -*-
"""
otp.py — אימות דו-שלבי בסמס לפני כל קליטת ספק

הרעיון: אף ספק לא נכנס לפריוריטי בלי שמישהו אישר זאת בקוד חד-פעמי שנשלח
לטלפון. הקוד קשור לרשומה *הספציפית* — אם הנתונים משתנים אחרי האימות, האישור
בטל וצריך לאמת שוב. כך אי אפשר לאשר ספק אחד ולטעון אחר.

מה נשמר במסד: רק גיבוב של הקוד (PBKDF2 עם מלח), זמן תפוגה, מספר ניסיונות
וטביעת אצבע של הנתונים. הקוד עצמו לא נשמר בשום מקום.

ערוצי שליחה (נבחרים במסך ההגדרות):
  console  — לפיתוח: הקוד נכתב ליומן השרת ומוצג במסך (רק בהרצה מקומית)
  webhook  — POST JSON לכתובת שלכם (מתאים לכל שער סמס ישראלי)
  inforu   — Inforu (uapi.inforu.co.il)
  twilio   — Twilio Programmable SMS
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import ssl
import urllib.error
import urllib.parse
import urllib.request

from . import security, store

log = logging.getLogger("intake.otp")

CODE_LENGTH = 6
MAX_ATTEMPTS = 5
SEND_TIMEOUT = 20

# מגבלות קצב: שליחות קוד לכל משתמש, וניסיונות אימות לכל משתמש
send_limiter = security.RateLimiter(limit=5, window_seconds=10 * 60)
verify_limiter = security.RateLimiter(limit=15, window_seconds=10 * 60)


class OtpError(Exception):
    """תקלה בשליחת הקוד או באימותו — עם הודעה בעברית למשתמש."""


def payload_fingerprint(screen, values):
    """
    טביעת אצבע של הרשומה שעומדת להיטען. שינוי כלשהו בנתונים משנה את הערך,
    ולכן מבטל אישור OTP קודם.
    """
    canonical = json.dumps({"screen": screen, "values": values},
                           ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generate_code():
    """קוד בן 6 ספרות ממקור אקראי קריפטוגרפי."""
    return f"{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}"


def resolve_phone(user, requested, config):
    """
    קובע לאיזה מספר יישלח הקוד, לפי מדיניות ההגדרות:
      otp_phone_mode=user — רק הטלפון הרשום למשתמש (ברירת מחדל, המאובטח יותר)
      otp_phone_mode=free — המשתמש רשאי להזין מספר אחר
    """
    user_phone = store.normalize_phone(user.get("phone"))
    requested = store.normalize_phone(requested)
    if (config.get("otp_phone_mode") or "user") == "user":
        if not user_phone:
            raise OtpError("לא הוגדר מספר טלפון למשתמש הזה. פנו למנהל המערכת "
                           "כדי להגדיר מספר לקבלת קודי אימות.")
        if requested and requested != user_phone:
            raise OtpError("המדיניות מתירה שליחת קוד רק למספר הרשום למשתמש.")
        return user_phone
    phone = requested or user_phone
    if not phone:
        raise OtpError("יש להזין מספר טלפון לקבלת הקוד.")
    return phone


def send_code(user, phone, screen, values, config):
    """
    מייצר קוד, שולח אותו, ורושם אותו במסד.
    מחזיר dict: {otp_id, phone_masked, channel, ttl_minutes, dev_code}
    (dev_code מוחזר רק בערוץ console ובהרצה מקומית).
    """
    phone = resolve_phone(user, phone, config)

    allowed, wait = send_limiter.check(f"user:{user['id']}")
    if not allowed:
        raise OtpError(f"נשלחו יותר מדי קודים. נסו שוב בעוד {wait} שניות.")

    code = generate_code()
    salt = secrets.token_hex(8)
    ttl = int(config.get("otp_ttl_minutes") or 5)
    channel = config.get("otp_channel") or "console"

    otp_id = store.create_otp(
        user_id=user["id"], phone=phone,
        code_hash=security.hash_code(code, salt), salt=salt,
        payload_hash=payload_fingerprint(screen, values),
        channel=channel, ttl_minutes=ttl)

    message = (f"קוד האימות לקליטת ספק בפריוריטי: {code}\n"
               f"תקף ל-{ttl} דקות. אם לא ביקשתם — התעלמו.")
    try:
        _dispatch(channel, phone, code, message, config)
    except OtpError:
        raise
    except Exception as exc:  # noqa: BLE001 — כל תקלת ספק חיצוני
        log.exception("OTP send failed")
        raise OtpError(f"שליחת הקוד נכשלה: {exc}") from exc

    send_limiter.record(f"user:{user['id']}")

    result = {
        "otp_id": otp_id,
        "phone_masked": security.mask_phone(phone),
        "channel": channel,
        "ttl_minutes": ttl,
    }
    if channel == "console" and _dev_visible():
        result["dev_code"] = code
    return result


def verify_code(user, otp_id, code, screen, values):
    """
    בודק קוד שהוזן. מחזיר את רשומת ה-OTP המאומתת, או זורק OtpError.
    """
    allowed, wait = verify_limiter.check(f"user:{user['id']}")
    if not allowed:
        raise OtpError(f"יותר מדי ניסיונות אימות. נסו שוב בעוד {wait} שניות.")
    verify_limiter.record(f"user:{user['id']}")

    record = store.get_otp(otp_id)
    if not record or record["user_id"] != user["id"]:
        raise OtpError("לא נמצא קוד פעיל. שלחו קוד חדש.")
    if record["consumed_at"]:
        raise OtpError("הקוד הזה כבר שימש לטעינה. שלחו קוד חדש.")
    if int(record["attempts"] or 0) >= MAX_ATTEMPTS:
        raise OtpError("הקוד ננעל לאחר יותר מדי ניסיונות. שלחו קוד חדש.")
    if _expired(record):
        raise OtpError("תוקף הקוד פג. שלחו קוד חדש.")
    if record["payload_hash"] != payload_fingerprint(screen, values):
        raise OtpError("פרטי הספק השתנו מאז שליחת הקוד. שלחו קוד חדש כדי לאשר "
                       "את הנתונים המעודכנים.")

    digits = "".join(ch for ch in str(code or "") if ch.isdigit())
    expected = record["code_hash"]
    if not digits or not hmac.compare_digest(security.hash_code(digits, record["salt"]), expected):
        store.bump_otp_attempts(otp_id)
        left = MAX_ATTEMPTS - int(record["attempts"] or 0) - 1
        if left <= 0:
            raise OtpError("הקוד שגוי והניסיונות אזלו. שלחו קוד חדש.")
        raise OtpError(f"הקוד שגוי. נותרו {left} ניסיונות.")

    store.mark_otp(otp_id, "verified_at")
    return store.get_otp(otp_id)


def check_verified(user, otp_id, screen, values):
    """
    מוודא לפני השליחה לפריוריטי שיש אישור OTP תקף לרשומה *הזו*.
    מחזיר את רשומת ה-OTP או זורק OtpError.
    """
    record = store.get_otp(otp_id) if otp_id else None
    if not record or record["user_id"] != user["id"] or not record["verified_at"]:
        raise OtpError("נדרש אימות בסמס לפני טעינת הספק.")
    if record["consumed_at"]:
        raise OtpError("האישור כבר שימש לטעינה. שלחו קוד חדש.")
    if _expired(record):
        raise OtpError("תוקף האישור פג. שלחו קוד חדש.")
    if record["payload_hash"] != payload_fingerprint(screen, values):
        raise OtpError("פרטי הספק השתנו אחרי האימות. שלחו קוד חדש.")
    return record


def _expired(record):
    import datetime as _dt
    try:
        expires = _dt.datetime.strptime(record["expires_at"], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return True
    return _dt.datetime.now() > expires


def _dev_visible():
    """הצגת הקוד על המסך מותרת רק בהרצה מקומית ובאישור מפורש."""
    hosted = bool(os.environ.get("VERCEL") or os.environ.get("RENDER"))
    return not hosted and (os.environ.get("INTAKE_OTP_DEBUG", "1").lower()
                           not in ("0", "false", "no", "off"))


# ---------------------------------------------------------------------------
# ערוצי שליחה
# ---------------------------------------------------------------------------
def _dispatch(channel, phone, code, message, config):
    sender = _SENDERS.get(channel)
    if sender is None:
        raise OtpError(f"ערוץ שליחה לא מוכר: {channel}")
    sender(phone, code, message, config)


def _post(url, data, headers, timeout=SEND_TIMEOUT):
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        raise OtpError(f"שער הסמס החזיר שגיאה (HTTP {exc.code}): {body}") from exc
    except urllib.error.URLError as exc:
        raise OtpError(f"לא ניתן להגיע לשער הסמס: {exc.reason}") from exc


def _send_console(phone, code, message, config):
    """פיתוח בלבד — הקוד נכתב ליומן השרת."""
    log.warning("OTP for %s: %s", security.mask_phone(phone), code)
    print(f"\n[OTP] קוד אימות עבור {security.mask_phone(phone)}: {code}\n", flush=True)


def _send_webhook(phone, code, message, config):
    """POST כללי — מתאים לכל שער סמס. הגוף: {phone, code, message, sender}."""
    url = (config.get("otp_endpoint") or "").strip()
    if not url:
        raise OtpError("לא הוגדרה כתובת webhook לשליחת סמס.")
    payload = json.dumps({
        "phone": phone,
        "code": code,
        "message": message,
        "sender": config.get("otp_sender_name") or "",
    }, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json;charset=utf-8"}
    token = config.get("otp_secret") or ""
    if token:
        headers["Authorization"] = token if token.lower().startswith(("bearer ", "basic ")) \
            else f"Bearer {token}"
    _post(url, payload, headers)


def _send_inforu(phone, code, message, config):
    """Inforu — שער סמס ישראלי נפוץ (uapi.inforu.co.il)."""
    user = (config.get("otp_user") or "").strip()
    token = config.get("otp_secret") or ""
    if not user or not token:
        raise OtpError("חסרים שם משתמש או טוקן של Inforu.")
    url = (config.get("otp_endpoint") or "https://uapi.inforu.co.il/api/v2/SMS/SendSms").strip()
    body = json.dumps({
        "Data": {
            "Message": message,
            "Recipients": [{"Phone": phone}],
            "Settings": {"Sender": config.get("otp_sender_name") or "Priority"},
        }
    }, ensure_ascii=False).encode("utf-8")
    auth = base64.b64encode(f"{user}:{token}".encode()).decode()
    status, raw = _post(url, body, {
        "Content-Type": "application/json;charset=utf-8",
        "Authorization": f"Basic {auth}",
    })
    _raise_if_failed_json(raw, ok_keys=("StatusId", "Status"), ok_values=(1, "1"))


def _send_twilio(phone, code, message, config):
    """Twilio Programmable SMS."""
    sid = (config.get("otp_user") or "").strip()
    token = config.get("otp_secret") or ""
    sender = (config.get("otp_sender_name") or "").strip()
    if not sid or not token or not sender:
        raise OtpError("חסרים Account SID, Auth Token או מספר שולח של Twilio.")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{urllib.parse.quote(sid)}/Messages.json"
    body = urllib.parse.urlencode({"To": phone, "From": sender, "Body": message}).encode()
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    _post(url, body, {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {auth}",
    })


def _raise_if_failed_json(raw, ok_keys, ok_values):
    """בדיקת תשובת ספק שמחזיר 200 גם על כישלון לוגי."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return
    if not isinstance(data, dict):
        return
    for key in ok_keys:
        if key in data and data[key] not in ok_values:
            detail = data.get("StatusDescription") or data.get("Description") or raw[:200]
            raise OtpError(f"שער הסמס דחה את השליחה: {detail}")


_SENDERS = {
    "console": _send_console,
    "webhook": _send_webhook,
    "inforu": _send_inforu,
    "twilio": _send_twilio,
}

CHANNEL_LABELS = {
    "console": "יומן השרת (פיתוח בלבד)",
    "webhook": "Webhook — שער סמס משלכם",
    "inforu": "Inforu",
    "twilio": "Twilio",
}
