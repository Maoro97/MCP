# -*- coding: utf-8 -*-
"""
priority.py — לקוח OData לכתיבה אל Priority ERP

הממשק שולח רשומה אחת בכל פעם דרך ה-REST API של פריוריטי:

    POST https://{host}/odata/Priority/{tabula.ini}/{company}/SUPPLIERS

שיטות ההזדהות הנתמכות (נבחרות במסך ההגדרות):
  • token  — Personal Access Token מטופס "REST Interface Access Tokens"
             (v19.1+). נשלח כ-Basic כאשר ה-token הוא שם המשתמש והסיסמה
             היא המילה הקבועה `PAT`.
  • user   — משתמש API מטופס "עובדים" (שם משתמש API + סיסמה) כ-Basic רגיל.
  • bearer — טוקן גישה מוכן (OAuth) בכותרת Authorization: Bearer.

אין כאן שום תלות חיצונית — הכל על urllib, כדי שהפריסה תישאר קלה.
"""

import base64
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_TIMEOUT = 30

# כתובת שירות תקינה: https://<שרת>[/<נתיב>]/odata/Priority/<tabula.ini>/<company>
_URL_RE = re.compile(
    r"^https?://[^/\s]+/(?:[^\s]+/)?odata/Priority/[^/\s]+/[^/\s]+$", re.I)


class PriorityError(Exception):
    """שגיאה שחוזרת מפריוריטי או מהתקשורת מולו — עם הסבר בעברית."""

    def __init__(self, message, status=None, detail=""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.detail = detail


def normalize_url(url):
    """מנקה את כתובת השירות: בלי רווחים ובלי / בסוף."""
    return (url or "").strip().rstrip("/")


def looks_like_service_url(url):
    """בדיקה מקדימה שהכתובת נראית כמו שורש שירות OData של פריוריטי."""
    return bool(_URL_RE.match(normalize_url(url)))


def _basic(user, password):
    raw = f"{user}:{password}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


class PriorityClient:
    """לקוח דק ל-OData של פריוריטי: קריאה, בדיקת חיבור ויצירת רשומה."""

    def __init__(self, url, auth_method="token", token="", username="",
                 password="", verify_tls=True, timeout=DEFAULT_TIMEOUT):
        self.url = normalize_url(url)
        self.auth_method = auth_method or "token"
        self.token = (token or "").strip()
        self.username = (username or "").strip()
        self.password = password or ""
        self.verify_tls = bool(verify_tls)
        self.timeout = timeout

    # -- הזדהות ---------------------------------------------------------
    def auth_header(self):
        if self.auth_method == "token":
            if not self.token:
                raise PriorityError("לא הוגדר טוקן גישה לפריוריטי")
            # פריוריטי מצפה ל-Basic עם הטוקן כשם המשתמש והמילה PAT כסיסמה
            return _basic(self.token, "PAT")
        if self.auth_method == "user":
            if not self.username:
                raise PriorityError("לא הוגדר שם משתמש API לפריוריטי")
            return _basic(self.username, self.password)
        if self.auth_method == "bearer":
            if not self.token:
                raise PriorityError("לא הוגדר טוקן גישה לפריוריטי")
            return f"Bearer {self.token}"
        raise PriorityError(f"שיטת הזדהות לא מוכרת: {self.auth_method}")

    def _ssl_context(self):
        if self.verify_tls:
            return ssl.create_default_context()
        # שרתי on-prem רבים בישראל עובדים עם תעודה עצמית. ההשבתה מפורשת
        # ומודעת — מסך ההגדרות מציג אזהרה כשהיא פעילה.
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    # -- שכבת התקשורת ---------------------------------------------------
    def _request(self, method, path, body=None, query=None, accept="application/json",
                 parse="json"):
        if not self.url:
            raise PriorityError("לא הוגדרה כתובת שירות לפריוריטי")

        url = f"{self.url}/{path.lstrip('/')}" if path else self.url
        if query:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query, safe="$'() ,=")

        data = None
        headers = {
            "Authorization": self.auth_header(),
            "Accept": accept,
            "User-Agent": "priority-supplier-intake/1.0",
        }
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json;charset=utf-8"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout,
                                        context=self._ssl_context()) as response:
                raw = response.read().decode("utf-8", "replace")
                if parse == "text":
                    return response.status, raw
                return response.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            raise PriorityError(_http_message(exc.code, raw), status=exc.code,
                                detail=raw[:1500]) from exc
        except urllib.error.URLError as exc:
            raise PriorityError(_network_message(exc), detail=str(exc.reason)) from exc
        except ssl.SSLError as exc:
            raise PriorityError(
                "שגיאת אבטחה (SSL) בחיבור לפריוריטי. אם השרת עובד עם תעודה "
                "עצמית — סמנו 'דלג על אימות תעודת SSL' בהגדרות.",
                detail=str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise PriorityError(
                "פריוריטי החזיר תשובה שאינה JSON — בדקו שכתובת השירות מצביעה "
                "על שורש ה-OData ולא על עמוד אחר.", detail=str(exc)) from exc
        except TimeoutError as exc:
            raise PriorityError(
                f"פריוריטי לא הגיב תוך {self.timeout} שניות.", detail=str(exc)) from exc

    # -- פעולות ---------------------------------------------------------
    def test_connection(self, entity="SUPPLIERS"):
        """
        בודק שהחיבור עובד: קורא רשומה אחת מה-entity.
        מחזיר dict {ok, message, sample_count}.
        """
        status, payload = self._request("GET", entity, query={"$top": "1"})
        rows = payload.get("value") if isinstance(payload, dict) else None
        return {
            "ok": True,
            "status": status,
            "message": f"החיבור לפריוריטי תקין — הטבלה {entity} נגישה לקריאה.",
            "sample_count": len(rows) if isinstance(rows, list) else 0,
        }

    def find(self, entity, field, value, select=None, top=1):
        """מחפש רשומה לפי שדה מפתח. מחזיר רשימת רשומות (אולי ריקה)."""
        query = {
            "$filter": f"{field} eq '{_escape_odata(value)}'",
            "$top": str(int(top)),
        }
        if select:
            query["$select"] = ",".join(select)
        _status, payload = self._request("GET", entity, query=query)
        rows = payload.get("value") if isinstance(payload, dict) else None
        return rows if isinstance(rows, list) else []

    def create(self, entity, body):
        """יוצר רשומה חדשה. מחזיר את הרשומה כפי שפריוריטי החזיר אותה."""
        _status, payload = self._request("POST", entity, body=body)
        return payload if isinstance(payload, dict) else {}

    def entity_properties(self, entity):
        """
        שמות השדות שקיימים בפועל ב-OData עבור ה-entity, לפי $metadata.

        נחוץ כי ייצוא עמודות המסך רחב יותר מה-API: יש עמודות שמופיעות במסך
        בפריוריטי אך אינן חשופות כשדה ב-OData, ופריוריטי דוחה אותן בטעינה
        ("The property X does not exist on type ..."). ההשוואה הזו מאתרת את
        כולן מראש, במקום לגלות אותן אחת-אחת בכל ניסיון טעינה.
        """
        _status, raw = self._request("GET", "$metadata", accept="application/xml",
                                     parse="text")
        properties = parse_metadata_properties(raw, entity)
        if not properties:
            raise PriorityError(
                f"לא נמצאה הגדרה של הטבלה {entity} ב-$metadata של פריוריטי.")
        return properties


# ---------------------------------------------------------------------------
# תרגום שגיאות לשפה של המשתמש
# ---------------------------------------------------------------------------
def _escape_odata(value):
    """בריחה לערך מחרוזת ב-$filter (גרש בודד מוכפל)."""
    return str(value).replace("'", "''")


def _local_name(tag):
    """שם התג בלי מרחב השמות — ה-EDMX משתמש בכמה גרסאות namespace."""
    return tag.rsplit("}", 1)[-1]


def parse_metadata_properties(xml_text, entity):
    """מחזיר את שמות ה-Property של EntityType מסוים מתוך מסמך $metadata."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise PriorityError("לא ניתן לקרוא את $metadata של פריוריטי.",
                            detail=str(exc)) from exc

    for node in root.iter():
        if _local_name(node.tag) != "EntityType":
            continue
        if (node.get("Name") or "").upper() != entity.upper():
            continue
        return {child.get("Name") for child in node
                if _local_name(child.tag) == "Property" and child.get("Name")}
    return set()


def extract_priority_message(raw):
    """שולף את הודעת השגיאה מגוף התשובה של פריוריטי (JSON או טקסט)."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        text = re.sub(r"<[^>]+>", " ", raw or "")
        return " ".join(text.split())[:400]

    node = data.get("error") if isinstance(data, dict) else None
    if isinstance(node, dict):
        message = node.get("message")
        if isinstance(message, dict):
            message = message.get("value")
        if isinstance(message, str) and message.strip():
            return message.strip()[:400]
    if isinstance(data, dict) and isinstance(data.get("message"), str):
        return data["message"].strip()[:400]
    return ""


_STATUS_MESSAGES = {
    400: "פריוריטי דחה את הנתונים",
    401: "ההזדהות מול פריוריטי נכשלה — בדקו את הטוקן או את שם המשתמש והסיסמה",
    403: "אין הרשאה לפעולה הזו בפריוריטי — בדקו את הרשאות המשתמש על מסך הספקים",
    404: "הכתובת או הטבלה לא נמצאו בפריוריטי — בדקו את כתובת השירות ואת שם החברה",
    405: "פריוריטי לא מאפשר את הפעולה על הטבלה הזו",
    409: "הרשומה כבר קיימת בפריוריטי",
    500: "שגיאה בצד פריוריטי",
    503: "שירות ה-OData של פריוריטי אינו זמין כרגע",
}


def _http_message(status, raw):
    base = _STATUS_MESSAGES.get(status, f"פריוריטי החזיר שגיאה (HTTP {status})")
    detail = extract_priority_message(raw)
    return f"{base}: {detail}" if detail else base


def _network_message(exc):
    reason = str(getattr(exc, "reason", exc))
    if "certificate" in reason.lower() or "ssl" in reason.lower():
        return ("החיבור לפריוריטי נכשל בגלל תעודת אבטחה. אם השרת עובד עם תעודה "
                "עצמית — סמנו 'דלג על אימות תעודת SSL' בהגדרות.")
    if "name or service not known" in reason.lower() or "nodename" in reason.lower():
        return "לא נמצא שרת בכתובת שהוגדרה — בדקו את כתובת השירות."
    if "refused" in reason.lower():
        return "השרת של פריוריטי סירב לחיבור — בדקו כתובת, פורט וחומת אש."
    return f"לא ניתן להתחבר לפריוריטי: {reason}"
