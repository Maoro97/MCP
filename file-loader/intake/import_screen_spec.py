# -*- coding: utf-8 -*-
"""
import_screen_spec.py — המרת "עמודות המסך" מפריוריטי לקטלוג שדות (YAML)

בפריוריטי אפשר לייצא את רשימת עמודות המסך לאקסל (עמודת מסך / חובה / בוליאני /
טיפוס / רוחב / דיוק עשרוני / כותרת). הסקריפט הזה הופך את הייצוא הזה לקובץ
`intake/fields_<SCREEN>.yaml` — קטלוג השדות שממנו ממשק הקליטה בונה את הטופס
ואוכף את הוולידציות.

    python -m intake.import_screen_spec intake/screens/SUPPLIERS_columns.xlsx SUPPLIERS

כך אפשר להוסיף מסכים נוספים (לקוחות, פריטים) בלי לכתוב שורת קוד.

מיפוי העמודות באקסל:
    עמודת מסך          -> שם השדה בפריוריטי
    קריאה/חובה/יתרה    -> M = שדה חובה, R = שדה לקריאה בלבד (תיאור מחושב)
    בולאני?            -> Y = שדה דגל (Y/N)
    טיפוס              -> CHAR / RCHAR / INT / REAL / DATE
    רוחב               -> אורך מרבי בתווים
    דיוק עשרוני        -> מספר ספרות אחרי הנקודה
    כותרת              -> הכותרת בעברית שמוצגת למשתמש
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# כותרות אפשריות לכל עמודה בקובץ הייצוא (בפריוריטי הן עשויות להשתנות מעט)
_HEADERS = {
    "name": ["עמודת מסך", "שם עמודה", "column", "עמודה"],
    "flag": ["קריאה/חובה/יתרה", "חובה", "קריאה"],
    "boolean": ["בולאני?", "בוליאני?", "בולאני", "בוליאני"],
    "type": ["טיפוס", "סוג"],
    "width": ["רוחב", "אורך"],
    "decimals": ["דיוק עשרוני", "עשרוני", "דיוק"],
    "title": ["כותרת", "תאור", "תיאור"],
}

# טיפוסי פריוריטי -> טיפוס לוגי בקטלוג
_TYPE_MAP = {
    "CHAR": "text",
    "RCHAR": "text",
    "INT": "int",
    "REAL": "real",
    "DATE": "date",
}

# שדות שאינם ניתנים להזנה ידנית: מזהים פנימיים של פריוריטי (מפתחות זרים).
# הם מזוהים לפי כותרת שמסתיימת ב-"(ID)" או לפי שם השדה.
_SYSTEM_NAMES = {
    "SUP", "SUPSUP", "IVGUID", "CHANGES_EXEC", "CHARKEY1", "CHARKEY2",
    "FOLLOWUPIV", "FOLLOWUPUSER", "NSCUST", "MCUST", "CUST", "PROJ", "AGENT",
    "EXTTYPE", "STATUSTYPE", "STATTYPE", "FROMEDI", "RESTRICTEDBY",
    "RESTRICTEDDATE", "ADDRESSMAP",
}


def _norm(text):
    return str(text or "").replace("‏", "").replace("‎", "").strip()


def _header_index(header_row):
    """מאתר את מיקום כל עמודה לפי הכותרת (או לפי סדר ברירת המחדל)."""
    cells = [_norm(c) for c in header_row]
    index = {}
    for key, options in _HEADERS.items():
        for i, cell in enumerate(cells):
            if cell in options:
                index[key] = i
                break
    if "name" not in index:          # קובץ ללא כותרות מזוהות — סדר ברירת המחדל
        index = {"name": 0, "flag": 1, "boolean": 2, "type": 3,
                 "width": 4, "decimals": 5, "title": 6}
    return index


def _int_or_none(value):
    text = _norm(value)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_workbook(path, sheet=None):
    """קורא את קובץ עמודות המסך ומחזיר dict {field_name: attributes}."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("הקובץ ריק")

    idx = _header_index(rows[0])
    get = lambda row, key: (row[idx[key]] if key in idx and idx[key] < len(row) else None)

    fields = {}
    for row in rows[1:]:
        name = _norm(get(row, "name")).upper()
        if not name or name in fields:
            continue

        flag = _norm(get(row, "flag")).upper()
        ptype = _norm(get(row, "type")).upper()
        width = _int_or_none(get(row, "width"))
        decimals = _int_or_none(get(row, "decimals"))
        title = _norm(get(row, "title"))

        entry = {"title": title or name, "priority_type": ptype or ""}

        # טיפוס לוגי: לפי עמודת הטיפוס; אם היא ריקה — נגזר מדיוק עשרוני
        logical = _TYPE_MAP.get(ptype)
        if logical is None:
            logical = "real" if decimals else "text"
        entry["type"] = logical

        if logical in ("text",) and width:
            entry["max_length"] = width
        if logical in ("int", "real") and width:
            entry["max_length"] = width
        if decimals is not None and logical in ("int", "real"):
            entry["decimals"] = decimals
        if flag == "M":
            entry["required"] = True
        if flag == "R":
            entry["readonly"] = True
        if _norm(get(row, "boolean")).upper() == "Y":
            entry["boolean"] = True
            entry["type"] = "bool"
        if name in _SYSTEM_NAMES or title.endswith("(ID)"):
            entry["system"] = True

        fields[name] = entry
    return fields


def merge_titles(fields, fallback_spec):
    """
    משלים כותרות עברית לשדות שבייצוא הן ריקות, מתוך קטלוג קיים (specs/<SCREEN>.yaml).
    """
    for name, entry in fields.items():
        if entry.get("title") and entry["title"] != name:
            continue
        known = (fallback_spec or {}).get(name) or {}
        if known.get("title"):
            entry["title"] = known["title"]
    return fields


def _yaml_value(text):
    """מחזיר מחרוזת YAML בטוחה (ציטוט כשצריך)."""
    text = str(text)
    if text == "" or any(ch in text for ch in ":#\"'{}[],&*?|<>=!%@`") or text.strip() != text:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


_ORDER = ["title", "type", "priority_type", "max_length", "decimals",
          "required", "readonly", "boolean", "system"]


def dump_yaml(screen, fields, source):
    lines = [
        "# ============================================================================",
        f"# קטלוג שדות מסך {screen} בפריוריטי — נוצר אוטומטית מייצוא עמודות המסך.",
        f"# מקור: {source}",
        "# אין לערוך ידנית — הרץ מחדש:",
        f"#   python -m intake.import_screen_spec intake/screens/... {screen}",
        "#",
        "# required = שדה חובה (M) · readonly = שדה לקריאה בלבד (R, תיאור מחושב)",
        "# system   = מזהה פנימי של פריוריטי — לא מוצג בטופס ולא נשלח",
        "# ============================================================================",
        f"screen: {screen}",
        f"source: {_yaml_value(source)}",
        "fields:",
    ]
    for name in fields:
        lines.append(f"  {name}:")
        entry = fields[name]
        for key in _ORDER:
            if key not in entry:
                continue
            value = entry[key]
            if isinstance(value, bool):
                lines.append(f"    {key}: {'true' if value else 'false'}")
            elif isinstance(value, int):
                lines.append(f"    {key}: {value}")
            else:
                lines.append(f"    {key}: {_yaml_value(value)}")
    return "\n".join(lines) + "\n"


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    path, screen = argv[1], argv[2].upper()
    sheet = argv[3] if len(argv) > 3 else None

    fields = parse_workbook(path, sheet)

    # השלמת כותרות מקטלוג קיים, אם יש
    fallback = {}
    legacy = os.path.join(HERE, "..", "specs", f"{screen}.yaml")
    if os.path.exists(legacy):
        import yaml
        with open(legacy, encoding="utf-8") as fh:
            fallback = (yaml.safe_load(fh) or {}).get("fields") or {}
    merge_titles(fields, fallback)

    out = os.path.join(HERE, f"fields_{screen}.yaml")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(dump_yaml(screen, fields, os.path.basename(path)))

    required = [n for n, f in fields.items() if f.get("required")]
    readonly = [n for n, f in fields.items() if f.get("readonly")]
    print(f"✅ נכתבו {len(fields)} שדות אל {out}")
    print(f"   חובה: {len(required)} ({', '.join(required)})")
    print(f"   לקריאה בלבד: {len(readonly)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
