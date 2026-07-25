# -*- coding: utf-8 -*-
"""
validators.py — ולידציות על ערכי התאים

כל פונקציית ולידציה מקבלת ערך (מחרוזת, אחרי ניקיון וטרנספורמציה) ומחזירה:
    None                 -> הערך תקין
    "טקסט שגיאה בעברית"   -> הערך פסול, עם סיבה מובנת למיישם

הבדיקה של כפילויות במפתח נעשית ברמת כל הקובץ (ראו check_duplicates)
ולא ברמת התא הבודד.

הודעות השגיאה מנוסחות למיישם — ברור, קצר, בעברית, בלי מונחים טכניים.
"""

import re


def validate_required(value: str, column: dict):
    """בדיקת שדה חובה — הערך אסור שיהיה ריק."""
    if column.get("required") and value == "":
        return f"שדה חובה '{column['target']}' ריק"
    return None


def validate_max_length(value: str, column: dict):
    """בדיקת אורך מקסימלי — לפי מגבלת השדה בפריוריטי."""
    max_len = column.get("max_length")
    if max_len is not None and len(value) > int(max_len):
        return (
            f"השדה '{column['target']}' חורג מהאורך המרבי "
            f"({len(value)} תווים מתוך {max_len} מותרים): '{value}'"
        )
    return None


def validate_number(value: str, column: dict):
    """
    בדיקת פורמט מספרי — לשדות מסוג type: number.
    מניחים שהערך כבר עבר ניקיון (הסרת מפרידי אלפים וכו') ב-transforms.
    ערך ריק נחשב תקין כאן (חובה נבדק בנפרד).
    """
    if column.get("type") != "number" or value == "":
        return None
    # מספר תקין: אופציונלי סימן, ספרות, אופציונלי נקודה עשרונית
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", value):
        return f"השדה '{column['target']}' אינו מספר תקין: '{value}'"
    return None


def validate_boolean(value: str, column: dict):
    """
    בדיקת שדה בוליאני (דגל) לפי קטלוג פריוריטי — הערך חייב להיות Y או N
    (או ריק). ערך אחר יגרום לכשל טעינה בפריוריטי, לכן נחשב שגיאה.
    """
    if not column.get("boolean") or value == "":
        return None
    if value not in ("Y", "N"):
        return (
            f"שדה דגל (בוליאני) '{column['target']}' חייב להיות Y או N (או ריק): '{value}'"
        )
    return None


def validate_value_map(value: str, column: dict):
    """
    בדיקת ערך מול value_map.
    ערך ריק מטופל מראש ב-transforms (מוחלף ב-default), כך שכאן ריק=תקין.
    ערך שאינו קיים ברשימה המותרת נחשב פסול.
    """
    value_map = column.get("value_map")
    if not value_map or value == "":
        return None
    # הערך כבר מופה — נבדוק שהוא אחד מערכי הפלט האפשריים (כולל default)
    allowed = set(value_map.values())
    default = column.get("default")
    if default is not None:
        allowed.add(str(default))
    if value not in allowed:
        allowed_src = ", ".join(f"'{k}'" for k in value_map.keys())
        return (
            f"ערך לא מוכר בשדה '{column['target']}': '{value}'. "
            f"הערכים המותרים במקור: {allowed_src}"
        )
    return None


# רשימת הוולידציות שרצות על כל תא, לפי הסדר.
_CELL_VALIDATORS = [
    validate_required,
    validate_max_length,
    validate_number,
    validate_boolean,
    validate_value_map,
]


def validate_cell(value: str, column: dict):
    """
    מריץ את כל ולידציות התא לפי הסדר ומחזיר את השגיאה הראשונה (או None).
    שגיאת תאריך מטופלת מוקדם יותר (ב-transforms.parse_date) ומועברת לכאן
    דרך הפרמטר date_error של validate_row.
    """
    for validator in _CELL_VALIDATORS:
        error = validator(value, column)
        if error:
            return error
    return None


# ---------------------------------------------------------------------------
# בדיקות פורמט (format) — למשל טלפון/דוא"ל. ברירת המחדל: אזהרה (לא פסילה).
# להוספת בדיקה חדשה: כתוב פונקציה שמחזירה True/False, והוסף אותה ל-FORMAT_CHECKS.
# ---------------------------------------------------------------------------
def is_valid_il_phone(digits: str) -> bool:
    """
    בדיקת מספר טלפון ישראלי (על מחרוזת ספרות בלבד):
    - נייד: 10 ספרות שמתחילות ב-05 או 07
    - קווי: 9 ספרות שמתחילות ב-0 וספרה שנייה 2/3/4/8/9
    - מוקדים: 1-800 / 1-700 / 1-599
    - קידומת בינ"ל 972 מנורמלת ל-0
    """
    d = digits
    if not d.isdigit():
        return False
    if d.startswith("972"):
        d = "0" + d[3:]
    if len(d) == 10 and d[:2] in ("05", "07"):
        return True
    if len(d) == 9 and d[0] == "0" and d[1] in "234689":
        return True
    if d[:4] in ("1800", "1700", "1599") and len(d) in (9, 10):
        return True
    return False


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value))


def is_valid_il_id(value: str) -> bool:
    """
    בדיקת ספרת ביקורת של מספר ישראלי (ת"ז / ח.פ. / עוסק מורשה) —
    אלגוריתם ה-checksum הרשמי (וריאנט Luhn). מקבל עד 9 ספרות.
    """
    d = "".join(ch for ch in value if ch.isdigit())
    if not d or len(d) > 9:
        return False
    d = d.zfill(9)
    total = 0
    for i, ch in enumerate(d):
        n = int(ch) * (1 if i % 2 == 0 else 2)
        total += n if n < 10 else n - 9
    return total % 10 == 0


def is_valid_il_zip(value: str) -> bool:
    """מיקוד ישראלי תקין — 7 ספרות (מיקוד חדש) או 5 ספרות (ישן)."""
    d = "".join(ch for ch in value if ch.isdigit())
    return len(d) in (5, 7)


# כל בדיקה: (פונקציה, טקסט האזהרה)
FORMAT_CHECKS = {
    "phone": (is_valid_il_phone, "מספר טלפון לא תקין"),
    "email": (is_valid_email, "כתובת דוא\"ל לא תקינה"),
    "idnum": (is_valid_il_id, "מספר ח.פ./עוסק לא תקין (ספרת ביקורת)"),
    "zip": (is_valid_il_zip, "מיקוד לא תקין"),
}


def validate_format(value: str, column: dict):
    """
    מריץ בדיקת פורמט (אם הוגדרה בעמודה) ומחזיר (הודעה, חומרה) או None.
    חומרה: 'warning' (ברירת מחדל — לא פוסל את השורה) או 'error' (פוסל).
    ערך ריק נחשב תקין (חובה נבדק בנפרד).
    """
    fmt = column.get("format")
    if not fmt or value == "":
        return None
    check = FORMAT_CHECKS.get(fmt)
    if not check:
        return None
    func, label = check
    if func(value):
        return None
    severity = column.get("format_severity", "warning")
    return f"{label} בשדה '{column['target']}': '{value}'", severity


def check_duplicates(rows, key_fields, columns):
    """
    בודק כפילויות על שדות המפתח (key_fields) בין כל השורות התקינות.
    - rows: רשימת dict-ים {target: value} של השורות שעברו ולידציית תא
    - key_fields: רשימת שמות שדות היעד המרכיבים את המפתח
    - columns: הגדרת העמודות (לצורך בדיקה ששדות המפתח קיימים)

    מחזיר dict: {אינדקס_שורה: "סיבת פסילה"} עבור כל שורה כפולה (מלבד הראשונה).
    """
    if not key_fields:
        return {}

    targets = {c["target"] for c in columns}
    missing = [k for k in key_fields if k not in targets]
    if missing:
        raise ValueError(
            "שדות המפתח (key_fields) הבאים אינם מוגדרים בעמודות המיפוי: "
            + ", ".join(missing)
        )

    seen = {}
    duplicates = {}
    for idx, row in rows:
        key = tuple(row.get(k, "") for k in key_fields)
        if key in seen:
            key_str = " | ".join(str(x) for x in key)
            duplicates[idx] = (
                f"כפילות במפתח ({', '.join(key_fields)}): '{key_str}' "
                f"— מופיע גם בשורה {seen[key] + 1}"
            )
        else:
            seen[key] = idx
    return duplicates
