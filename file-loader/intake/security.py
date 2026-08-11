# -*- coding: utf-8 -*-
"""
security.py — סיסמאות, הצפנת סודות ומגבלות קצב

שלוש אחריות:
  1. גיבוב סיסמאות (PBKDF2-SHA256 עם מלח אקראי לכל משתמש).
  2. הצפנת סודות במסד — הטוקן של פריוריטי לא נשמר בטקסט גלוי. המפתח מגיע
     ממשתנה הסביבה, ולכן גניבת קובץ המסד לבדה אינה חושפת את הטוקן.
  3. מגבלת קצב (rate limit) פשוטה בזיכרון, לניסיונות התחברות ולשליחת קודי OTP.

ההצפנה מיושמת על ספריות התקן בלבד (hashlib/hmac) — CTR עם HMAC-SHA256
כפונקציית הזרם, ואימות encrypt-then-MAC. אין תלות חיצונית ואין קריפטוגרפיה
מומצאת: זו הרכבה סטנדרטית של פרימיטיבים תקניים.
"""

import base64
import hashlib
import hmac
import os
import secrets
import struct
import threading
import time

PBKDF2_ROUNDS = 240_000
_SALT_BYTES = 16
_NONCE_BYTES = 16
_TAG_BYTES = 32


# ---------------------------------------------------------------------------
# סיסמאות
# ---------------------------------------------------------------------------
def hash_password(password, salt=None, rounds=PBKDF2_ROUNDS):
    """מחזיר מחרוזת אחסון: pbkdf2_sha256$<rounds>$<salt-b64>$<hash-b64>."""
    salt = salt or secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return "pbkdf2_sha256${}${}${}".format(
        rounds, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify_password(password, stored):
    """בדיקת סיסמה מול הערך השמור, בהשוואה עמידה למדידת זמן."""
    try:
        algo, rounds, salt_b64, hash_b64 = (stored or "").split("$")
        if algo != "pbkdf2_sha256":
            return False
        expected = base64.b64decode(hash_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                     base64.b64decode(salt_b64), int(rounds))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def password_problem(password):
    """מדיניות סיסמה מינימלית. מחזיר טקסט שגיאה בעברית או None."""
    if len(password or "") < 10:
        return "הסיסמה חייבת להכיל לפחות 10 תווים"
    if password.isdigit() or password.isalpha():
        return "הסיסמה חייבת לשלב אותיות וספרות"
    return None


# ---------------------------------------------------------------------------
# הצפנת סודות במסד
# ---------------------------------------------------------------------------
def _master_key():
    """
    מפתח ההצפנה של הסודות. מגיע ממשתנה סביבה בלבד — כך שהוא לא נמצא במסד.
    """
    raw = (os.environ.get("INTAKE_SECRET") or os.environ.get("SECRET_KEY")
           or os.environ.get("APP_SECRET") or "")
    if not raw:
        return None
    return hashlib.sha256(raw.encode("utf-8")).digest()


def secrets_encrypted():
    """האם יש מפתח להצפנת סודות (אחרת הם נשמרים בטקסט גלוי — עם אזהרה בממשק)."""
    return _master_key() is not None


def _keystream(key, nonce, length):
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(key, nonce + struct.pack(">I", counter), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def encrypt_secret(plaintext):
    """מצפין סוד לאחסון. ללא מפתח — מחזיר את הערך בתחילית `plain:`."""
    if plaintext is None:
        plaintext = ""
    key = _master_key()
    if key is None:
        return "plain:" + plaintext
    data = plaintext.encode("utf-8")
    nonce = secrets.token_bytes(_NONCE_BYTES)
    cipher = bytes(a ^ b for a, b in zip(data, _keystream(key, nonce, len(data))))
    tag = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    return "enc:" + base64.b64encode(nonce + cipher + tag).decode()


def decrypt_secret(stored):
    """מפענח סוד מהמסד. מחזיר "" אם הערך פגום או שהמפתח השתנה."""
    if not stored:
        return ""
    if stored.startswith("plain:"):
        return stored[len("plain:"):]
    if not stored.startswith("enc:"):
        return stored          # ערך ישן שנשמר לפני שהוצפן
    key = _master_key()
    if key is None:
        return ""
    try:
        blob = base64.b64decode(stored[len("enc:"):])
    except (ValueError, TypeError):
        return ""
    if len(blob) < _NONCE_BYTES + _TAG_BYTES:
        return ""
    nonce, cipher, tag = (blob[:_NONCE_BYTES],
                          blob[_NONCE_BYTES:-_TAG_BYTES],
                          blob[-_TAG_BYTES:])
    if not hmac.compare_digest(hmac.new(key, nonce + cipher, hashlib.sha256).digest(), tag):
        return ""
    return bytes(a ^ b for a, b in zip(cipher, _keystream(key, nonce, len(cipher)))).decode(
        "utf-8", "replace")


def hash_code(code, salt):
    """גיבוב קוד ה-OTP לאחסון — הקוד עצמו לעולם אינו נשמר."""
    return hashlib.pbkdf2_hmac("sha256", str(code).encode(), salt.encode(), 60_000).hex()


def mask_phone(phone):
    """הסתרת אמצע מספר הטלפון להצגה בממשק וביומן: 050-•••-4321."""
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if len(digits) < 6:
        return "•" * len(digits)
    return f"{digits[:3]}•••{digits[-3:]}"


# ---------------------------------------------------------------------------
# מגבלת קצב בזיכרון
# ---------------------------------------------------------------------------
class RateLimiter:
    """
    מגביל פעולות לפי מפתח (שם משתמש / כתובת IP) בחלון זמן נע.
    מיועד לתהליך יחיד (worker אחד, כמו בהגדרת הפריסה של הפרויקט).
    """

    def __init__(self, limit, window_seconds):
        self.limit = limit
        self.window = window_seconds
        self._hits = {}
        self._lock = threading.Lock()

    def check(self, key):
        """מחזיר (מותר, שניות_להמתנה)."""
        now = time.time()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < self.window]
            self._hits[key] = hits
            if len(hits) >= self.limit:
                return False, int(self.window - (now - hits[0])) + 1
            return True, 0

    def record(self, key):
        now = time.time()
        with self._lock:
            self._hits.setdefault(key, []).append(now)
            if len(self._hits) > 5000:      # ניקוי תקופתי כדי לא לצבור זיכרון
                for k in list(self._hits):
                    self._hits[k] = [t for t in self._hits[k] if now - t < self.window]
                    if not self._hits[k]:
                        del self._hits[k]

    def reset(self, key):
        with self._lock:
            self._hits.pop(key, None)
