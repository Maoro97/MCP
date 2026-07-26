# -*- coding: utf-8 -*-
"""
transforms.py — טרנספורמציות וניקיון נתונים אוטומטי

המודול אחראי על:
1. ניקיון אוטומטי של כל תא (רווחים, תווי RTL/LRM נסתרים, BOM וכו')
2. המרת ערכים שאקסל שמר "לא נכון" (מספר כטקסט, תאריך כמספר סריאלי)
3. טרנספורמציות בשם (strip, upper, lower וכו') שניתן להפעיל דרך קובץ המיפוי
4. עיצוב תאריכים לפורמט הפלט שמוגדר במיפוי

כל הפונקציות מקבלות ערך ומחזירות ערך — הן אינן זורקות שגיאות ולידציה.
הוולידציות עצמן נמצאות ב-validators.py.
"""

import re
import datetime as _dt

import pandas as pd


# ---------------------------------------------------------------------------
# ניקיון תווים נסתרים
# ---------------------------------------------------------------------------

# תווי כיווניות (RTL/LTR) ותווים בלתי־נראים שאקסל / העתקה מהאינטרנט משאירים.
# הם "מלכלכים" את הנתונים וגורמים לאי־התאמות במפתחות ובוולידציות.
_HIDDEN_CHARS = (
    "‎"  # LRM  – Left-to-Right Mark
    "‏"  # RLM  – Right-to-Left Mark
    "؜"  # ALM  – Arabic Letter Mark
    "​"  # ZWSP – Zero Width Space
    "‌"  # ZWNJ
    "‍"  # ZWJ
    "⁠"  # Word Joiner
    "﻿"  # BOM / ZWNBSP
    "‪‫‬‭‮"  # LRE/RLE/PDF/LRO/RLO
    "⁦⁧⁨⁩"        # LRI/RLI/FSI/PDI
)
_HIDDEN_RE = re.compile("[" + _HIDDEN_CHARS + "]")

# רווחים "מיוחדים" שיש להמיר לרווח רגיל לפני צמצום רווחים.
_NBSP_RE = re.compile("[   \t]")


def strip_hidden(value: str) -> str:
    """מסיר תווי כיווניות ותווים בלתי־נראים ממחרוזת."""
    return _HIDDEN_RE.sub("", value)


def clean_whitespace(value: str) -> str:
    """
    ניקיון רווחים:
    - המרת רווחים מיוחדים (NBSP, טאב) לרווח רגיל
    - צמצום רצפי רווחים לרווח בודד
    - הסרת רווחים מקצוות
    """
    value = _NBSP_RE.sub(" ", value)
    value = re.sub(r" {2,}", " ", value)
    return value.strip()


def auto_clean(value) -> str:
    """
    ניקיון אוטומטי שמופעל על *כל* תא לפני כל טרנספורמציה אחרת.
    מקבל ערך גולמי (מחרוזת / מספר / None) ומחזיר מחרוזת נקייה.
    ערך ריק (None / NaN) מוחזר כמחרוזת ריקה.
    """
    if value is None:
        return ""
    # pandas מחזיר NaN עבור תאים ריקים
    try:
        if isinstance(value, float) and pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    text = value if isinstance(value, str) else _stringify_raw(value)
    text = strip_hidden(text)
    text = clean_whitespace(text)
    return text


def _stringify_raw(value) -> str:
    """
    המרת ערך לא־מחרוזתי (מספר / תאריך) למחרוזת בצורה "נקייה":
    - מספר שלם שנשמר כ-float (3.0) יוצג בלי הנקודה (3)
    - datetime יוצג בפורמט ISO (יעובד בהמשך אם השדה מסוג date)
    """
    if isinstance(value, bool):
        return "Y" if value else "N"
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return repr(value)
    if isinstance(value, (_dt.datetime, _dt.date, pd.Timestamp)):
        return _to_datetime(value).isoformat()
    return str(value)


# ---------------------------------------------------------------------------
# המרת מספרים (כולל מספרים שאקסל שמר כטקסט)
# ---------------------------------------------------------------------------

_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}(\D|$))")


def to_number_string(text: str, decimals=None) -> str:
    """
    מנקה ערך מספרי שאקסל שמר כטקסט ומחזיר מחרוזת מספרית תקנית.
    - מסיר מפרידי אלפים (1,234 -> 1234)
    - מסיר סימני מטבע ורווחים
    - תומך במספרים שליליים ובנקודה עשרונית
    - decimals (אם ניתן): מספר ספרות אחרי הנקודה בפלט
    מחזיר מחרוזת ריקה אם הקלט ריק. אם ההמרה נכשלת — מחזיר את הקלט כמו שהוא
    (הוולידציה של type=number תתפוס אותו כשגיאה).
    """
    if text == "":
        return ""
    raw = text
    # הסרת סימני מטבע נפוצים ורווחים
    raw = raw.replace("₪", "").replace("$", "").replace("€", "").replace("%", "")
    raw = raw.replace(" ", "")
    # הסרת מפרידי אלפים
    raw = _THOUSANDS_RE.sub("", raw)

    try:
        num = float(raw)
    except ValueError:
        return text  # לא הצליח — יטופל בוולידציה

    if decimals is not None:
        return f"{num:.{int(decimals)}f}"
    if num.is_integer():
        return str(int(num))
    # ניקוי אפסים מיותרים בזנב
    return ("%f" % num).rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# המרת תאריכים (כולל תאריך שאקסל שמר כמספר סריאלי)
# ---------------------------------------------------------------------------

# פורמטים שכיחים בקבצי מקור בישראל, ננסה אותם לפי הסדר.
_DATE_INPUT_FORMATS = [
    "%d/%m/%Y", "%d/%m/%y",
    "%d.%m.%Y", "%d.%m.%y",
    "%d-%m-%Y", "%d-%m-%y",
    "%Y-%m-%d", "%Y/%m/%d",
]

# מערכת התאריכים של אקסל: הסידורי 1 = 1900-01-01, אך עם באג השנה המעוברת
# 1900 — לכן ה-origin הנכון לחישוב הוא 1899-12-30.
_EXCEL_EPOCH = _dt.datetime(1899, 12, 30)


def _to_datetime(value) -> _dt.datetime:
    """המרת ערך תאריכי (Timestamp / date / datetime) ל-datetime רגיל."""
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, _dt.datetime):
        return value
    if isinstance(value, _dt.date):
        return _dt.datetime(value.year, value.month, value.day)
    return value


def parse_date(raw_value, output_format: str):
    """
    מקבל ערך גולמי (datetime / מספר סריאלי / מחרוזת) ומחזיר טאפל:
        (מחרוזת_מעוצבת, שגיאה)
    - אם ההמרה הצליחה: (str, None)
    - אם נכשלה:        ("", "טקסט שגיאה")
    - אם ריק:          ("", None)
    """
    # 1) ערך ריק
    if raw_value is None:
        return "", None
    if isinstance(raw_value, float) and pd.isna(raw_value):
        return "", None
    if isinstance(raw_value, str) and raw_value.strip() == "":
        return "", None

    # 2) אקסל שמר את התאריך כאובייקט תאריך אמיתי
    if isinstance(raw_value, (pd.Timestamp, _dt.datetime, _dt.date)):
        return _to_datetime(raw_value).strftime(output_format), None

    # 3) אקסל שמר את התאריך כמספר סריאלי (float/int)
    if isinstance(raw_value, (int, float)):
        try:
            dt = _EXCEL_EPOCH + _dt.timedelta(days=float(raw_value))
            return dt.strftime(output_format), None
        except (OverflowError, ValueError):
            return "", f"ערך תאריך לא תקין: {raw_value}"

    # 4) מחרוזת — ננסה מספר פורמטים מקובלים
    text = auto_clean(raw_value)
    # ייתכן שהמחרוזת היא בעצם מספר סריאלי ("45000")
    if re.fullmatch(r"\d+(\.\d+)?", text):
        try:
            dt = _EXCEL_EPOCH + _dt.timedelta(days=float(text))
            return dt.strftime(output_format), None
        except (OverflowError, ValueError):
            pass
    for fmt in _DATE_INPUT_FORMATS:
        try:
            dt = _dt.datetime.strptime(text, fmt)
            return dt.strftime(output_format), None
        except ValueError:
            continue
    return "", f"פורמט תאריך לא מזוהה: '{text}'"


# ---------------------------------------------------------------------------
# טרנספורמציות בשם — ניתנות להפעלה דרך המיפוי (transform: [strip, upper])
# ---------------------------------------------------------------------------

NAMED_TRANSFORMS = {
    "strip": lambda v: v.strip(),
    "upper": lambda v: v.upper(),
    "lower": lambda v: v.lower(),
    "title": lambda v: v.title(),
    "collapse_spaces": clean_whitespace,
    "digits_only": lambda v: re.sub(r"\D", "", v),
    "remove_spaces": lambda v: v.replace(" ", ""),
    "blank_if_zero": lambda v: "" if _is_zero(v) else v,   # אסמכתא 0 -> ריק
    "abs": lambda v: _abs_str(v),                          # ערך מוחלט (חיובי)
}


def _is_zero(v: str) -> bool:
    """האם הערך הוא אפס מספרי (0 / 0.0 / -0 וכו')."""
    s = v.strip().replace(",", "")
    try:
        return float(s) == 0
    except (ValueError, TypeError):
        return False


def _abs_str(v: str) -> str:
    """מחזיר את הערך המספרי בערך מוחלט (מסיר סימן מינוס). לא-מספרי — ללא שינוי."""
    s = v.strip().replace(",", "")
    try:
        n = float(s)
    except (ValueError, TypeError):
        return v
    n = abs(n)
    return str(int(n)) if n.is_integer() else ("%f" % n).rstrip("0").rstrip(".")


def apply_named_transforms(value: str, names) -> str:
    """מפעיל רשימת טרנספורמציות בשם על מחרוזת, לפי הסדר."""
    for name in names or []:
        func = NAMED_TRANSFORMS.get(name)
        if func is None:
            # מיפוי שגוי — נזרוק שגיאה ברורה שתטופל ב-main
            raise ValueError(
                f"טרנספורמציה לא מוכרת בקובץ המיפוי: '{name}'. "
                f"הטרנספורמציות הזמינות: {', '.join(sorted(NAMED_TRANSFORMS))}"
            )
        value = func(value)
    return value
