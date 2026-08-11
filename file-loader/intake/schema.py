# -*- coding: utf-8 -*-
"""
schema.py — קטלוג השדות, מבנה הטופס והוולידציה בצד השרת

שני מקורות אמת:
  • `fields_<SCREEN>.yaml`  — קטלוג השדות שנוצר מייצוא עמודות המסך בפריוריטי
                              (חובה / אורך / טיפוס / בוליאני / לקריאה בלבד).
  • `form_<SCREEN>.yaml`    — איך הטופס נראה: שלבים, סדר, כותרות, רשימות ערכים.

כל ולידציה שרצה בדפדפן רצה **גם כאן**. הדפדפן הוא נוחות בלבד; השרת הוא
שער הכניסה לפריוריטי, ולכן הוא בודק מחדש כל שדה: קיום בקטלוג, הרשאת כתיבה,
חובה, אורך, טיפוס, וערכי דגל.
"""

import datetime as _dt
import functools
import os

import yaml

import transforms
import validators

HERE = os.path.dirname(os.path.abspath(__file__))
LOOKUPS_DIR = os.path.join(HERE, "..", "lookups")

# פורמט התאריך שנשלח לפריוריטי (OData Edm.DateTimeOffset)
ODATA_DATE_FORMAT = "%Y-%m-%dT00:00:00Z"


class SchemaError(Exception):
    """תקלה בהגדרות הטופס עצמן (לא בנתוני המשתמש)."""


def _read_yaml(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@functools.lru_cache(maxsize=8)
def load_catalog(screen):
    """קטלוג השדות של המסך: {FIELD: {title, type, max_length, required, ...}}."""
    path = os.path.join(HERE, f"fields_{screen}.yaml")
    if not os.path.exists(path):
        raise SchemaError(f"לא נמצא קטלוג שדות למסך {screen}")
    return _read_yaml(path).get("fields") or {}


@functools.lru_cache(maxsize=8)
def load_form(screen):
    """מבנה הטופס של המסך."""
    path = os.path.join(HERE, f"form_{screen}.yaml")
    if not os.path.exists(path):
        raise SchemaError(f"לא נמצא מבנה טופס למסך {screen}")
    return _read_yaml(path)


@functools.lru_cache(maxsize=8)
def available_screens():
    """המסכים שיש להם גם קטלוג שדות וגם מבנה טופס."""
    screens = []
    for name in sorted(os.listdir(HERE)):
        if name.startswith("form_") and name.endswith(".yaml"):
            screen = name[len("form_"):-len(".yaml")]
            if os.path.exists(os.path.join(HERE, f"fields_{screen}.yaml")):
                screens.append(screen)
    return screens


@functools.lru_cache(maxsize=16)
def load_lookup(name):
    """טבלת עזר מ-lookups/<name>.csv (עמודות code,desc) -> [(code, desc)]."""
    import csv

    path = os.path.join(LOOKUPS_DIR, f"{name}.csv")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for line_no, parts in enumerate(csv.reader(fh)):
            parts = [p.strip() for p in parts]
            if line_no == 0 and parts and parts[0].lower() == "code":
                continue
            if parts and parts[0]:
                rows.append((parts[0], parts[1] if len(parts) > 1 else parts[0]))
    return rows


# ---------------------------------------------------------------------------
# בניית מודל התצוגה של הטופס
# ---------------------------------------------------------------------------
def _resolve_field(screen, entry, catalog):
    """מאחד הגדרת שדה מהטופס עם הכללים מהקטלוג -> dict מוכן לתצוגה ולוולידציה."""
    name = entry.get("field")
    if not name:
        raise SchemaError("הגדרת שדה בטופס ללא מפתח 'field'")
    meta = catalog.get(name)
    if meta is None:
        raise SchemaError(f"השדה '{name}' אינו קיים בקטלוג של מסך {screen}")
    if meta.get("readonly"):
        raise SchemaError(f"השדה '{name}' הוא לקריאה בלבד ואי אפשר לטעון אליו")
    if meta.get("system"):
        raise SchemaError(f"השדה '{name}' הוא מזהה פנימי של פריוריטי")

    # `type` ו-`required` בטופס גוברים על הקטלוג. `type` נחוץ לשדות שבייצוא
    # עמודות המסך עמודת הטיפוס שלהם ריקה; `required` נחוץ כי לא כל שדה שמסומן
    # חובה *במסך* הוא חובה גם ב-API — פריוריטי נשאר הסמכות, ואם הוא כן ידרוש
    # את השדה, הדחייה שלו תוצג למשתמש כמו כל שגיאה אחרת.
    field = {
        "name": name,
        "label": entry.get("label") or meta.get("title") or name,
        "type": entry.get("type") or meta.get("type", "text"),
        "required": bool(entry["required"] if "required" in entry else meta.get("required")),
        "max_length": meta.get("max_length"),
        "decimals": meta.get("decimals"),
        "boolean": bool(meta.get("boolean")),
        "help": entry.get("help", ""),
        "placeholder": entry.get("placeholder", ""),
        "width": entry.get("width", "half"),
        "default": entry.get("default", ""),
        "format": entry.get("format"),
        "transform": entry.get("transform") or [],
        "options": None,
        "show_codes": False,
    }

    # שדה דגל (Y/N) מוצג תמיד כבחירה — כן / לא
    if field["boolean"] or field["type"] == "bool" or (
            field["type"] == "text" and field["max_length"] == 1 and name.endswith("FLAG")):
        field["boolean"] = True
        field["type"] = "bool"
        field["options"] = [("Y", "כן"), ("N", "לא")]
    elif entry.get("options_file"):
        # ברשימות קוד-ותיאור (מטבעות, תנאי תשלום) הקוד עצמו מעניין את המשתמש,
        # כי הוא זה שנשמר בפריוריטי — לכן מוצג לצד התיאור.
        field["options"] = load_lookup(entry["options_file"])
        field["show_codes"] = True
    elif entry.get("options"):
        field["options"] = [(str(v), str(v)) for v in entry["options"]]

    return field


def build_form(screen, include_advanced=False):
    """
    מחזיר את מבנה הטופס לתצוגה:
        {screen, entity, key_field, title, subtitle, steps: [{id,title,icon,hint,fields:[...]}]}
    """
    form = load_form(screen)
    catalog = load_catalog(screen)

    steps = []
    for step in form.get("steps") or []:
        steps.append({
            "id": step.get("id") or f"step{len(steps) + 1}",
            "title": step.get("title", ""),
            "icon": step.get("icon", ""),
            "hint": step.get("hint", ""),
            "fields": [_resolve_field(screen, f, catalog) for f in step.get("fields") or []],
        })

    advanced = form.get("advanced") or {}
    if include_advanced and advanced.get("fields"):
        steps.append({
            "id": "advanced",
            "title": advanced.get("title", "שדות נוספים"),
            "icon": advanced.get("icon", "⚙️"),
            "hint": advanced.get("hint", ""),
            "fields": [_resolve_field(screen, f, catalog) for f in advanced["fields"]],
        })

    return {
        "screen": screen,
        "entity": form.get("entity") or screen,
        "key_field": form.get("key_field"),
        "title": form.get("title") or screen,
        "subtitle": form.get("subtitle", ""),
        "steps": steps,
    }


def form_fields(screen, include_advanced=False):
    """כל שדות הטופס כמילון {name: field} — לוולידציה."""
    out = {}
    for step in build_form(screen, include_advanced)["steps"]:
        for field in step["fields"]:
            out[field["name"]] = field
    return out


# ---------------------------------------------------------------------------
# ולידציה של ערך בודד
# ---------------------------------------------------------------------------
_TRUE_WORDS = {"Y", "כן", "TRUE", "1", "YES", "V", "✓"}
_FALSE_WORDS = {"N", "לא", "FALSE", "0", "NO", ""}


def clean_value(field, raw):
    """ניקוי + טרנספורמציות + נרמול לפי טיפוס. מחזיר (value, error)."""
    value = transforms.auto_clean(raw)
    if field["transform"]:
        value = transforms.apply_named_transforms(value, field["transform"])
    if value == "" and field.get("default") not in (None, ""):
        value = str(field["default"])

    if value == "":
        return "", None

    kind = field["type"]
    if kind == "bool":
        upper = value.upper()
        if upper in _TRUE_WORDS:
            return "Y", None
        if upper in _FALSE_WORDS:
            return "N", None
        return value, f"הערך של '{field['label']}' חייב להיות כן או לא"

    if kind in ("int", "real"):
        # לשדה שלם לא מעגלים בשקט — 3.5 בשדה "ימים" הוא טעות של המשתמש,
        # ועדיף שיתקן אותה בעצמו מאשר שנכריע עבורו.
        decimals = None if kind == "int" else field.get("decimals")
        numeric = transforms.to_number_string(value, decimals)
        if not _is_number(numeric):
            return value, f"'{field['label']}' אינו מספר תקין: {value}"
        if kind == "int" and "." in numeric:
            return value, f"'{field['label']}' חייב להיות מספר שלם (ללא שבר): {value}"
        return numeric, None

    if kind == "date":
        formatted, error = transforms.parse_date(value, "%Y-%m-%d")
        if error:
            return value, f"'{field['label']}': {error}"
        return formatted, None

    return value, None


def _is_number(text):
    try:
        float(text)
        return True
    except (TypeError, ValueError):
        return False


def validate_value(field, raw):
    """
    בודק ערך בודד. מחזיר (value, error, warning):
      error   — חוסם את הטעינה
      warning — מוצג למשתמש אך אינו חוסם (פורמט טלפון/דוא"ל/ח.פ./מיקוד)
    """
    value, error = clean_value(field, raw)
    if error:
        return value, error, None

    if field["required"] and value == "":
        return value, f"'{field['label']}' הוא שדה חובה", None

    max_length = field.get("max_length")
    if max_length and field["type"] in ("text", "bool") and len(value) > int(max_length):
        return (value,
                f"'{field['label']}' ארוך מדי — {len(value)} תווים מתוך {max_length} מותרים",
                None)

    warning = None
    fmt = field.get("format") or ""
    check = validators.FORMAT_CHECKS.get(fmt)
    if check and value:
        func, label = check
        # בדיקת הטלפון עובדת על ספרות בלבד, אבל את מה שהמשתמש הקליד משאירים
        # כמו שהוא — "03-1234567" הוא מספר תקין לגמרי, וגם ככה ייכנס לפריוריטי.
        subject = _digits(value) if fmt == "phone" else value
        if not func(subject):
            warning = f"{label} בשדה '{field['label']}'"

    return value, error, warning


def _digits(text):
    return "".join(ch for ch in text if ch.isdigit())


def validate_payload(screen, data, include_advanced=False):
    """
    בודק את כל הטופס.
    מחזיר (values, errors, warnings) — כולם dict לפי שם שדה.
    שדה שאינו חלק מהטופס נדחה כשגיאה (הגנה מפני הזרקת שדות).
    """
    fields = form_fields(screen, include_advanced)
    values, errors, warnings = {}, {}, {}

    for name in data:
        if name not in fields:
            errors[name] = f"השדה '{name}' אינו חלק מטופס הקליטה"

    for name, field in fields.items():
        value, error, warning = validate_value(field, data.get(name, ""))
        values[name] = value
        if error:
            errors[name] = error
        if warning:
            warnings[name] = warning

    return values, errors, warnings


def to_odata(screen, values, include_advanced=False):
    """
    ממיר את הערכים שעברו ולידציה לגוף JSON עבור OData של פריוריטי:
    מספרים כמספרים, תאריכים בפורמט ISO, ושדות ריקים אינם נשלחים כלל
    (כדי לא לדרוס ברירות מחדל של פריוריטי).
    """
    fields = form_fields(screen, include_advanced)
    body = {}
    for name, value in values.items():
        field = fields.get(name)
        if field is None or value == "":
            continue
        kind = field["type"]
        if kind == "int":
            body[name] = int(float(value))
        elif kind == "real":
            body[name] = float(value)
        elif kind == "date":
            body[name] = _dt.datetime.strptime(value, "%Y-%m-%d").strftime(ODATA_DATE_FORMAT)
        else:
            body[name] = value
    return body
