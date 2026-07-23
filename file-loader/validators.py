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
