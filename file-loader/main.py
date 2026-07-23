# -*- coding: utf-8 -*-
"""
main.py — כלי הכנת קבצי טעינה לממשקי File Load של Priority ERP

הכלי מקבל קובץ אקסל גולמי + קובץ מיפוי (YAML) של מסך יעד, ומייצר:
  1. קובץ טעינה מוכן ל-Interface בפריוריטי  (output/<SCREEN>_load.<ext>)
  2. קובץ שורות פסולות לתיקון והרצה חוזרת    (output/<SCREEN>_rejected.xlsx)
  3. דוח סיכום בעברית                          (output/<SCREEN>_report.txt + מסך)

שימוש:
  python main.py --input customers.xlsx --screen CUSTOMERS [--sheet "גיליון1"] [--dry-run]

הכלי מיועד למיישמים: הודעות שגיאה ברורות בעברית, בלי stack traces.
"""

import argparse
import os
import sys
import datetime as _dt
from collections import Counter

import pandas as pd
import yaml

import transforms
import validators


# ---------------------------------------------------------------------------
# שגיאה "ידידותית" — כשמשהו לא תקין בקלט/מיפוי, נציג הודעה ברורה ולא stack trace
# ---------------------------------------------------------------------------
class UserError(Exception):
    pass


HERE = os.path.dirname(os.path.abspath(__file__))
MAPPINGS_DIR = os.path.join(HERE, "mappings")
OUTPUT_DIR = os.path.join(HERE, "output")

# פורמט התאריך בפלט — תמיד dd/mm/yy (למשל 23/07/26).
# זהו מקור האמת היחיד: אם קובץ מיפוי לא מציין date_format, זה מה שיחול.
DEFAULT_DATE_FORMAT = "%d/%m/%y"

# מפרידים אפשריים בקובץ הפלט
_DELIMITERS = {"tab": "\t", "comma": ",", "pipe": "|"}
# קידודים נתמכים (שם ידידותי -> שם קידוד של פייתון)
_ENCODINGS = {"windows-1255": "cp1255", "utf-8": "utf-8"}
# סיומת קובץ הפלט לפי המפריד
_EXTENSIONS = {"tab": "txt", "comma": "csv", "pipe": "txt"}


def _norm_header(text) -> str:
    """נרמול כותרת עמודה לצורך התאמה (הסרת תווים נסתרים ורווחים מיותרים)."""
    return transforms.clean_whitespace(transforms.strip_hidden(str(text)))


# ---------------------------------------------------------------------------
# טעינת קובץ המיפוי + בדיקת תקינותו
# ---------------------------------------------------------------------------
def load_mapping(screen: str) -> dict:
    path = os.path.join(MAPPINGS_DIR, f"{screen}.yaml")
    if not os.path.exists(path):
        # גם תמיכה בסיומת .yml
        alt = os.path.join(MAPPINGS_DIR, f"{screen}.yml")
        if os.path.exists(alt):
            path = alt
        else:
            available = _list_available_screens()
            raise UserError(
                f"לא נמצא קובץ מיפוי למסך '{screen}'.\n"
                f"היה אמור להיות: mappings/{screen}.yaml\n"
                f"מסכים קיימים: {available or '(אין)'}"
            )
    try:
        with open(path, "r", encoding="utf-8") as f:
            mapping = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise UserError(f"שגיאת תחביר בקובץ המיפוי '{path}':\n{e}")

    _validate_mapping(mapping, path)
    return mapping


def available_screens() -> list:
    """מחזיר רשימת שמות המסכים הזמינים (לפי קבצי המיפוי) — לשימוש ה-CLI והוובי."""
    if not os.path.isdir(MAPPINGS_DIR):
        return []
    names = [
        os.path.splitext(f)[0]
        for f in os.listdir(MAPPINGS_DIR)
        if f.endswith((".yaml", ".yml"))
    ]
    return sorted(names)


def _list_available_screens() -> str:
    return ", ".join(available_screens())


def rows_from_dataframe(df, mapping, resolved):
    """הופך DataFrame לרשימת שורות {target: ערך_גולמי} לפי מיפוי העמודות."""
    columns = mapping["columns"]
    rows = []
    for _, r in df.iterrows():
        row = {}
        for col in columns:
            actual = resolved.get(col["target"])
            row[col["target"]] = r[actual] if actual is not None else None
        rows.append(row)
    return rows


def evaluate_grid(mapping, input_rows, reserved_keys=None, excel_rows=None):
    """
    ליבת "טבלת הטעינה" — מקבלת שורות של {target: ערך} (גולמי מהאקסל או
    ערוך מהמשתמש), מריצה עיבוד + ולידציה על *כל תא בנפרד*, ומחזירה רשימת
    שורות עם הערך המעובד וסיבת השגיאה לכל תא. כפילויות מסמנות את תאי המפתח.

    reserved_keys: קבוצת מפתחות (tuples) של שורות תקינות ששמורות כבר בשרת
                   (בקבצים גדולים מוצגות למשתמש רק השורות השגויות) — שורה
                   שמפתחה מתנגש איתן תסומן ככפולה.
    excel_rows:    מספרי השורות המקוריים בקובץ (למצב "שגויות בלבד").

    כל שורה: {excel_row, valid, cells:[{target, value, error}]}
    """
    columns = mapping["columns"]
    date_format = mapping.get("date_format", DEFAULT_DATE_FORMAT)
    key_fields = mapping.get("key_fields") or []
    reserved_keys = reserved_keys or set()

    rows_out = []
    for i, row in enumerate(input_rows):
        cells = []
        row_valid = True
        for col in columns:
            value, err = process_value(row.get(col["target"]), col, date_format)
            if not err:
                err = validators.validate_cell(value, col)
            if err:
                row_valid = False
            cells.append({"target": col["target"], "value": value, "error": err})
        excel_row = excel_rows[i] if excel_rows else i + 2
        rows_out.append({"excel_row": excel_row, "cells": cells, "valid": row_valid})

    # בדיקת כפילויות בין השורות שתקינות עד כה — סימון תאי המפתח
    if key_fields:
        valid_pairs = [
            (idx, {c["target"]: c["value"] for c in r["cells"]})
            for idx, r in enumerate(rows_out) if r["valid"]
        ]
        dups = validators.check_duplicates(valid_pairs, key_fields, columns)
        for idx, reason in dups.items():
            rows_out[idx]["valid"] = False
            for c in rows_out[idx]["cells"]:
                if c["target"] in key_fields:
                    c["error"] = reason

        # התנגשות מול שורות תקינות שכבר שמורות בשרת
        if reserved_keys:
            for r in rows_out:
                if not r["valid"]:
                    continue
                key = tuple(
                    next(c["value"] for c in r["cells"] if c["target"] == k)
                    for k in key_fields
                )
                if key in reserved_keys:
                    r["valid"] = False
                    for c in r["cells"]:
                        if c["target"] in key_fields:
                            c["error"] = (
                                f"כפילות במפתח ({', '.join(key_fields)}): "
                                f"'{' | '.join(key)}' כבר קיים בשורות התקינות שנטענו"
                            )
    return rows_out


def row_key(cells, key_fields):
    """מחזיר את המפתח (tuple) של שורת טבלה לפי key_fields."""
    lut = {c["target"]: c["value"] for c in cells}
    return tuple(lut.get(k, "") for k in key_fields)


def grid_valid_records(rows_out):
    """מחזיר רשומות תקינות (עם values מסודרים) לבניית קובץ הטעינה מטבלת הטעינה."""
    return [
        {"values": [c["value"] for c in r["cells"]], "excel_row": r["excel_row"]}
        for r in rows_out if r["valid"]
    ]


def _expected_sources(mapping):
    """שמות עמודות המקור מהמיפוי — לצורך זיהוי אוטומטי של שורת הכותרת."""
    return [c["source"] for c in mapping["columns"] if c.get("source")]


def prepare(screen, source, sheet=None, header_row=None):
    """
    ליבת העיבוד המשותפת ל-CLI ולממשק הוובי.
    מקבל שם מסך, מקור אקסל (נתיב או file-like) ושם גיליון, ומחזיר dict עם
    כל תוצאות העיבוד — בלי לכתוב קבצים לדיסק (הקורא מחליט מה לעשות איתן).
    """
    mapping = load_mapping(screen)
    df = read_excel(
        source, sheet,
        header_row=header_row if header_row is not None else mapping.get("header_row"),
        expected_sources=_expected_sources(mapping),
    )
    resolved = build_column_lookup(df, mapping["columns"])

    records = process_rows(df, mapping, resolved)
    valid_records = [r for r in records if r["reason"] is None]
    rejected_records = [r for r in records if r["reason"] is not None]
    enc_warnings = check_encoding(
        valid_records, mapping["columns"], mapping.get("encoding", "windows-1255")
    )

    return {
        "mapping": mapping,
        "df": df,
        "records": records,
        "valid": valid_records,
        "rejected": rejected_records,
        "warnings": enc_warnings,
        "total": len(records),
    }


def _validate_mapping(mapping, path):
    """בדיקת תקינות מבנה קובץ המיפוי — לתפוס טעויות הגדרה מוקדם ובבירור."""
    if not isinstance(mapping, dict):
        raise UserError(f"קובץ המיפוי '{path}' אינו במבנה תקין (צריך YAML של מפתח:ערך).")

    columns = mapping.get("columns")
    if not columns or not isinstance(columns, list):
        raise UserError(f"קובץ המיפוי '{path}' חייב להכיל רשימת 'columns' לא ריקה.")

    delimiter = mapping.get("delimiter", "tab")
    if delimiter not in _DELIMITERS:
        raise UserError(
            f"מפריד לא נתמך '{delimiter}' בקובץ המיפוי. "
            f"אפשרויות: {', '.join(_DELIMITERS)}"
        )

    encoding = mapping.get("encoding", "windows-1255")
    if encoding not in _ENCODINGS:
        raise UserError(
            f"קידוד לא נתמך '{encoding}' בקובץ המיפוי. "
            f"אפשרויות: {', '.join(_ENCODINGS)}"
        )

    for i, col in enumerate(columns, start=1):
        if not isinstance(col, dict) or not col.get("target"):
            raise UserError(
                f"עמודה מס' {i} בקובץ המיפוי חסרה שדה 'target' (שם השדה בפריוריטי)."
            )
        ctype = col.get("type", "text")
        if ctype not in ("text", "number", "date"):
            raise UserError(
                f"סוג שדה לא נתמך '{ctype}' בעמודה '{col['target']}'. "
                f"אפשרויות: text, number, date"
            )


# ---------------------------------------------------------------------------
# קריאת קובץ האקסל
# ---------------------------------------------------------------------------
def detect_header_row(raw, expected_sources, scan=30):
    """
    מזהה את שורת הכותרת בקובץ שבו הכותרת אינה בהכרח בשורה הראשונה
    (קבצי יצוא רבים מוסיפים שורות כותרת/תאריך/לוגו מעל). האסטרטגיה:
    בוחרים את השורה (מבין הראשונות) שמכילה הכי הרבה משמות העמודות שבמיפוי.
    אם אין התאמה — נופלים לשורה הראשונה שאינה ריקה.
    מחזיר אינדקס (0-based).
    """
    expected = {_norm_header(s) for s in (expected_sources or []) if s}
    limit = min(scan, len(raw))

    best_idx, best_score = None, 0
    for i in range(limit):
        vals = {
            _norm_header(v)
            for v in raw.iloc[i].tolist()
            if v is not None and str(v).strip() != ""
        }
        if not vals:
            continue
        score = len(expected & vals)
        if score > best_score:
            best_score, best_idx = score, i

    if best_idx is not None and best_score >= 1:
        return best_idx

    # אין התאמה לשמות המיפוי — נשתמש בשורה הראשונה שאינה ריקה
    for i in range(limit):
        if any(v is not None and str(v).strip() != "" for v in raw.iloc[i].tolist()):
            return i
    return 0


def _build_unique_headers(header_vals):
    """הופך את שורת הכותרת לרשימת שמות עמודות ייחודיים ולא ריקים."""
    names, seen = [], {}
    for j, v in enumerate(header_vals):
        name = _norm_header(v) if v is not None and str(v).strip() != "" else f"עמודה_{j + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        names.append(name)
    return names


def read_excel(source, sheet, header_row=None, expected_sources=None):
    """
    קורא קובץ אקסל. source יכול להיות נתיב (str) או אובייקט קובץ בזיכרון
    (file-like) — כך שאותה פונקציה משרתת גם את ה-CLI וגם את הממשק הוובי.

    תומך בקבצים שבהם שורת הכותרת אינה הראשונה:
    - header_row (1-based) — לכפות שורת כותרת מפורשת.
    - אחרת — זיהוי אוטומטי לפי expected_sources (שמות העמודות במיפוי).
    """
    name = source if isinstance(source, str) else "הקובץ שהועלה"
    if isinstance(source, str) and not os.path.exists(source):
        raise UserError(f"קובץ הקלט לא נמצא: {source}")
    try:
        # קוראים ללא כותרת (header=None) כדי לאתר בעצמנו את שורת הכותרת
        raw = pd.read_excel(
            source,
            sheet_name=sheet if sheet is not None else 0,
            header=None,
            dtype=object,
            engine="openpyxl",
        )
    except ValueError as e:
        # לרוב: שם גיליון שגוי
        raise UserError(f"לא ניתן לקרוא את הגיליון '{sheet}' מ{name}.\n{e}")
    except Exception as e:  # noqa: BLE001 — נציג הודעה ידידותית במקום stack trace
        raise UserError(f"שגיאה בקריאת קובץ האקסל ({name}):\n{e}")

    if raw.empty:
        raise UserError(f"הגיליון ב{name} ריק — אין שורות לעיבוד.")

    # מיקום שורת הכותרת
    if header_row is not None:
        hidx = int(header_row) - 1
        if hidx < 0 or hidx >= len(raw):
            raise UserError(
                f"שורת הכותרת שצוינה ({header_row}) מחוץ לטווח הקובץ "
                f"(יש {len(raw)} שורות)."
            )
    else:
        hidx = detect_header_row(raw, expected_sources)

    columns = _build_unique_headers(raw.iloc[hidx].tolist())
    df = raw.iloc[hidx + 1:].copy()
    df.columns = columns
    # מסירים שורות ריקות לגמרי (נפוץ בסופי קבצי יצוא)
    df = df.dropna(how="all").reset_index(drop=True)

    if df.empty:
        raise UserError(
            f"לא נמצאו שורות נתונים מתחת לשורת הכותרת (שורה {hidx + 1}) ב{name}."
        )
    return df


def build_column_lookup(df, columns):
    """
    בונה מיפוי בין ה-source שבקובץ המיפוי לבין העמודה בפועל באקסל.
    זורק שגיאה ברורה אם עמודת מקור חסרה מהאקסל.
    """
    lookup = {_norm_header(c): c for c in df.columns}
    resolved = {}
    missing = []
    for col in columns:
        source = col.get("source")
        if source is None:
            continue  # עמודת ערך קבוע — אין מקור
        actual = lookup.get(_norm_header(source))
        if actual is None:
            missing.append(source)
        else:
            resolved[col["target"]] = actual
    if missing:
        raise UserError(
            "העמודות הבאות מוגדרות בקובץ המיפוי אך לא נמצאו בקובץ האקסל:\n  - "
            + "\n  - ".join(missing)
            + "\n\nעמודות שקיימות באקסל: "
            + ", ".join(_norm_header(c) for c in df.columns)
        )
    return resolved


# ---------------------------------------------------------------------------
# עיבוד ערך בודד: ניקיון -> המרת טיפוס -> טרנספורמציות -> value_map -> default
# ---------------------------------------------------------------------------
def process_value(raw, column, date_format):
    """
    מחזיר טאפל (value_str, error_or_None).
    error מוחזר רק עבור שגיאות שמתגלות כבר בשלב ההמרה (למשל תאריך פגום);
    שאר הוולידציות רצות בנפרד ב-validators.validate_cell.
    """
    # עמודת ערך קבוע (ללא source) — הערך הוא ה-default לכל השורות
    if column.get("source") is None:
        default = column.get("default", "")
        return "" if default is None else str(default), None

    ctype = column.get("type", "text")

    if ctype == "date":
        value, err = transforms.parse_date(raw, date_format)
        if err:
            return "", err
    else:
        value = transforms.auto_clean(raw)
        if ctype == "number":
            value = transforms.to_number_string(value, column.get("decimals"))
        value = transforms.apply_named_transforms(value, column.get("transform"))

    # מיפוי ערכים (value_map)
    value_map = column.get("value_map")
    default = column.get("default")
    if value_map is not None:
        if value == "":
            value = "" if default is None else str(default)
        elif value in value_map:
            value = str(value_map[value])
        # אחרת — נשאיר כמו שהוא; validate_value_map יסמן אותו כפסול
    else:
        if value == "" and default is not None:
            value = str(default)

    return value, None


def categorize_error(reason: str) -> str:
    """מסווג סיבת פסילה לקטגוריה כללית — לצורך דוח '10 השגיאות הנפוצות'."""
    if reason.startswith("שדה חובה"):
        return "שדות חובה חסרים"
    if "חורג מהאורך" in reason:
        return "חריגה מאורך מרבי"
    if "אינו מספר" in reason:
        return "מספר לא תקין"
    if "תאריך" in reason:
        return "תאריך לא תקין"
    if reason.startswith("ערך לא מוכר"):
        return "ערך מחוץ לרשימה המותרת"
    if reason.startswith("כפילות"):
        return "כפילות במפתח"
    return "אחר"


# ---------------------------------------------------------------------------
# עיבוד כל הקובץ
# ---------------------------------------------------------------------------
def process_rows(df, mapping, resolved):
    """
    מעבד את כל השורות ומחזיר רשומות עם הערכים המעובדים וסיבת פסילה (אם יש).
    כל רשומה: dict עם excel_row, values (רשימה מסודרת), row_dict, reason, original.
    """
    columns = mapping["columns"]
    date_format = mapping.get("date_format", DEFAULT_DATE_FORMAT)

    records = []
    for pos, (_, row) in enumerate(df.iterrows()):
        excel_row = pos + 2  # שורה 1 = כותרות, הנתונים מתחילים בשורה 2
        values = []
        row_dict = {}
        reason = None

        for col in columns:
            actual = resolved.get(col["target"])
            raw = row[actual] if actual is not None else None

            value, err = process_value(raw, col, date_format)

            if reason is None:
                e = err or validators.validate_cell(value, col)
                if e:
                    reason = e

            values.append(value)
            row_dict[col["target"]] = value

        records.append(
            {
                "excel_row": excel_row,
                "values": values,
                "row_dict": row_dict,
                "reason": reason,
                "original": row,
            }
        )

    # בדיקת כפילויות על השורות שעברו ולידציית תא (reason ריק)
    valid_pairs = [(i, r["row_dict"]) for i, r in enumerate(records) if r["reason"] is None]
    dup_map = validators.check_duplicates(
        valid_pairs, mapping.get("key_fields"), columns
    )
    for idx, dup_reason in dup_map.items():
        records[idx]["reason"] = dup_reason

    return records


# ---------------------------------------------------------------------------
# בדיקת התאמה לקידוד (windows-1255) — אזהרות על תווים לא ניתנים להמרה
# ---------------------------------------------------------------------------
def check_encoding(valid_records, columns, encoding_name):
    """
    בודק אילו תווים בשורות התקינות אינם ניתנים להמרה לקידוד היעד.
    מחזיר רשימת אזהרות (מחרוזות), עם ציון שורה ושדה.
    בקובץ הפלט התווים הבעייתיים יוחלפו ב-'?'.
    """
    py_enc = _ENCODINGS[encoding_name]
    if py_enc == "utf-8":
        return []  # utf-8 מכיל הכל

    warnings = []
    targets = [c["target"] for c in columns]
    for rec in valid_records:
        for field, value in zip(targets, rec["values"]):
            try:
                value.encode(py_enc)
            except UnicodeEncodeError:
                bad = sorted({ch for ch in value if not _encodable(ch, py_enc)})
                warnings.append(
                    f"שורה {rec['excel_row']}, שדה '{field}': "
                    f"תווים שלא ניתנים לקידוד {encoding_name}: "
                    f"{' '.join(repr(c) for c in bad)} — יוחלפו ב-'?'"
                )
    return warnings


def _encodable(ch, py_enc) -> bool:
    try:
        ch.encode(py_enc)
        return True
    except UnicodeEncodeError:
        return False


# ---------------------------------------------------------------------------
# כתיבת קובץ הטעינה
# ---------------------------------------------------------------------------
def reorder_for_export(valid_records, mapping, order_targets):
    """
    מסדר מחדש את העמודות לפי סדר מבוקש (order_targets — רשימת שמות target).
    מחזיר (רשומות_מסודרות, מיפוי_מסודר) כך שגם קובץ הטעינה וגם שורת הכותרת
    (אם include_header) יֵצאו בסדר הזה. עמודות שלא צוינו נוספות בסוף.
    """
    columns = mapping["columns"]
    tmap = {c["target"]: i for i, c in enumerate(columns)}
    order = [t for t in (order_targets or []) if t in tmap]
    order += [c["target"] for c in columns if c["target"] not in order]  # השלמת חוסרים
    idx = [tmap[t] for t in order]

    new_columns = [columns[i] for i in idx]
    new_records = [
        {"values": [r["values"][i] for i in idx], "excel_row": r.get("excel_row")}
        for r in valid_records
    ]
    new_mapping = dict(mapping)
    new_mapping["columns"] = new_columns
    return new_records, new_mapping


def build_load_content(valid_records, mapping) -> str:
    """בונה את תוכן קובץ הטעינה כמחרוזת (שורות מופרדות ב-CRLF)."""
    delimiter = _DELIMITERS[mapping.get("delimiter", "tab")]
    include_header = bool(mapping.get("include_header", False))
    columns = mapping["columns"]

    lines = []
    if include_header:
        lines.append(delimiter.join(c["target"] for c in columns))
    for rec in valid_records:
        lines.append(delimiter.join(rec["values"]))

    # שורות מופרדות ב-CRLF (תקן קבצי טקסט ב-Windows / פריוריטי און-פרם)
    content = "\r\n".join(lines)
    if lines:
        content += "\r\n"
    return content


def load_content_bytes(content: str, mapping) -> bytes:
    """מקודד את תוכן קובץ הטעינה לקידוד היעד (errors='replace' לתווים חריגים)."""
    encoding = _ENCODINGS[mapping.get("encoding", "windows-1255")]
    return content.encode(encoding, errors="replace")


def load_file_extension(mapping) -> str:
    return _EXTENSIONS[mapping.get("delimiter", "tab")]


def write_load_file(valid_records, mapping, screen):
    ext = load_file_extension(mapping)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"{screen}_load.{ext}")

    content = build_load_content(valid_records, mapping)
    with open(out_path, "wb") as f:
        f.write(load_content_bytes(content, mapping))

    return out_path


# ---------------------------------------------------------------------------
# כתיבת קובץ השורות הפסולות (rejected.xlsx)
# ---------------------------------------------------------------------------
def write_rejected_file(rejected_records, df, screen):
    """
    כותב את השורות הפסולות עם עמודות המקור המקוריות + עמודת 'סיבת פסילה',
    כדי שאפשר לתקן ולהריץ שוב רק אותן.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"{screen}_rejected.xlsx")
    build_rejected_df(rejected_records, df).to_excel(
        out_path, index=False, engine="openpyxl"
    )
    return out_path


def build_rejected_df(rejected_records, df):
    """בונה DataFrame של השורות הפסולות: עמודות המקור + 'שורה במקור' + 'סיבת פסילה'."""
    rows = []
    for rec in rejected_records:
        data = rec["original"].to_dict()
        data["סיבת פסילה"] = rec["reason"]
        data["שורה במקור"] = rec["excel_row"]
        rows.append(data)
    # שמירה על סדר העמודות המקורי + העמודות שהוספנו בסוף
    cols = list(df.columns) + ["שורה במקור", "סיבת פסילה"]
    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------------------
# דוח סיכום
# ---------------------------------------------------------------------------
def build_report(screen, mapping, total, valid_records, rejected_records,
                 enc_warnings, out_path, rejected_path, dry_run):
    lines = []
    add = lines.append

    add("=" * 60)
    add(f"  דוח הכנת קובץ טעינה — מסך {screen}")
    interface = mapping.get("interface_name")
    if interface:
        add(f"  Interface בפריוריטי: {interface}")
    add(f"  זמן ריצה: {_dt.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    add("=" * 60)
    add("")
    add(f"  שורות שנקראו:  {total}")
    add(f"  שורות תקינות:  {len(valid_records)}")
    add(f"  שורות שנפסלו:  {len(rejected_records)}")
    add("")

    # פירוט 10 השגיאות הנפוצות
    if rejected_records:
        counter = Counter(categorize_error(r["reason"]) for r in rejected_records)
        add("  פירוט השגיאות הנפוצות:")
        for i, (cat, cnt) in enumerate(counter.most_common(10), start=1):
            add(f"    {i}. {cat}: {cnt} שורות")
        add("")

    # אזהרות קידוד
    if enc_warnings:
        add(f"  אזהרות קידוד ({len(enc_warnings)}):")
        for w in enc_warnings[:20]:
            add(f"    ⚠  {w}")
        if len(enc_warnings) > 20:
            add(f"    ... ועוד {len(enc_warnings) - 20} אזהרות (ראו קובץ הדוח)")
        add("")

    # פלט
    if dry_run:
        add("  מצב --dry-run: בוצעה ולידציה בלבד, לא נוצר קובץ טעינה.")
    else:
        add(f"  קובץ טעינה:  {out_path}")
    if rejected_records:
        add(f"  שורות פסולות: {rejected_path}")
    add("=" * 60)

    return "\n".join(lines)


def write_report_file(report_text, enc_warnings, screen):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"{screen}_report.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_text)
        if enc_warnings:
            f.write("\n\nפירוט מלא של אזהרות הקידוד:\n")
            for w in enc_warnings:
                f.write(f"  - {w}\n")
    return out_path


# ---------------------------------------------------------------------------
# תזרים ראשי
# ---------------------------------------------------------------------------
def run(args):
    mapping = load_mapping(args.screen)
    df = read_excel(
        args.input, args.sheet,
        header_row=args.header_row if args.header_row is not None else mapping.get("header_row"),
        expected_sources=_expected_sources(mapping),
    )
    resolved = build_column_lookup(df, mapping["columns"])

    records = process_rows(df, mapping, resolved)
    valid_records = [r for r in records if r["reason"] is None]
    rejected_records = [r for r in records if r["reason"] is not None]

    enc_warnings = check_encoding(
        valid_records, mapping["columns"], mapping.get("encoding", "windows-1255")
    )

    out_path = None
    rejected_path = None

    if not args.dry_run and valid_records:
        out_path = write_load_file(valid_records, mapping, args.screen)

    if rejected_records:
        rejected_path = write_rejected_file(rejected_records, df, args.screen)

    report = build_report(
        args.screen, mapping, len(records), valid_records, rejected_records,
        enc_warnings, out_path, rejected_path, args.dry_run,
    )
    report_path = write_report_file(report, enc_warnings, args.screen)

    print(report)
    print(f"\nהדוח נשמר: {report_path}")

    # קוד יציאה: 0 אם הכל תקין, 1 אם היו שורות פסולות (נוח לאוטומציה)
    return 1 if rejected_records else 0


def main():
    parser = argparse.ArgumentParser(
        description="הכנת קובץ טעינה ל-Interface (File Load) של Priority ERP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", required=True, help="קובץ האקסל הגולמי (xlsx)")
    parser.add_argument(
        "--screen", required=True,
        help="שם המסך — נטען מ-mappings/<SCREEN>.yaml",
    )
    parser.add_argument("--sheet", default=None, help="שם הגיליון (ברירת מחדל: הראשון)")
    parser.add_argument(
        "--header-row", type=int, default=None, dest="header_row",
        help="מספר שורת הכותרת (החל מ-1). ברירת מחדל: זיהוי אוטומטי",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="ולידציה בלבד — בלי לייצר קובץ טעינה",
    )

    args = parser.parse_args()

    try:
        exit_code = run(args)
    except UserError as e:
        print(f"\n❌ שגיאה: {e}\n", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\nהריצה בוטלה על ידי המשתמש.", file=sys.stderr)
        sys.exit(130)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
