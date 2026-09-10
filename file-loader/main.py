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
import re
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
SPECS_DIR = os.path.join(HERE, "specs")
LOOKUPS_DIR = os.path.join(HERE, "lookups")

# תיקיית הפלט: ניתנת לדריסה במשתנה סביבה. בפלטפורמות serverless (Vercel) שאר
# מערכת הקבצים היא לקריאה-בלבד — ורק /tmp ניתן לכתיבה — לכן שם ברירת המחדל /tmp.
OUTPUT_DIR = (
    os.environ.get("FILE_LOADER_OUTPUT")
    or ("/tmp/fl-output" if os.environ.get("VERCEL") else os.path.join(HERE, "output"))
)
HISTORY_FILE = os.path.join(OUTPUT_DIR, "history.jsonl")

# מטמון למפרטי השדות (specs/<SCREEN>.yaml) וטבלאות lookup
_SPEC_CACHE = {}
_LOOKUP_CACHE = {}


def load_lookup(name):
    """
    טוען טבלת lookup מ-lookups/<name>.csv (עמודות code,desc).
    מחזיר dict מנורמל: {ערך_מנורמל: code} — תואם גם לקוד וגם לתיאור,
    כדי שהמערכת תזהה ערך שמגיע בכל צורה ותתאים לו את הקוד הנכון.
    """
    if name in _LOOKUP_CACHE:
        return _LOOKUP_CACHE[name]
    import csv
    table = {}
    path = os.path.join(LOOKUPS_DIR, f"{name}.csv")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    code = (row.get("code") or "").strip()
                    desc = (row.get("desc") or "").strip()
                    if not code:
                        continue
                    table[_norm_header(code)] = code
                    if desc:
                        table.setdefault(_norm_header(desc), code)
        except OSError:
            table = {}
    _LOOKUP_CACHE[name] = table
    return table


def lookup_value(name, value):
    """מתאים ערך (קוד/תיאור) לקוד לפי טבלת lookup. אם לא נמצא — מחזיר None."""
    if value == "":
        return ""
    return load_lookup(name).get(_norm_header(value))


_LOOKUP_PAIRS_CACHE = {}


def lookup_pairs(name):
    """מחזיר רשימת (code, desc) מטבלת lookups/<name>.csv, לפי סדר הקובץ."""
    if name in _LOOKUP_PAIRS_CACHE:
        return _LOOKUP_PAIRS_CACHE[name]
    import csv
    pairs, path = [], os.path.join(LOOKUPS_DIR, f"{name}.csv")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    code = (row.get("code") or "").strip()
                    if code:
                        pairs.append((code, (row.get("desc") or "").strip()))
        except OSError:
            pairs = []
    _LOOKUP_PAIRS_CACHE[name] = pairs
    return pairs


def append_history(entry):
    """מוסיף רשומת היסטוריה למסד הנתונים (SQLite) ומחזיר את מזהה הרשומה (id)."""
    import datetime as _dt
    import getpass
    import db as _db
    entry = dict(entry)
    entry.setdefault("ts", _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    if not entry.get("user"):
        try:
            entry["user"] = getpass.getuser()
        except Exception:  # noqa: BLE001
            entry["user"] = ""
    return _db.add_load(entry)


def read_history(limit=200, screen=None):
    """קורא את היסטוריית הטעינות מקובצת ל"קבצים" (אב→בן), עם לוג הגרסאות."""
    import db as _db
    return _db.list_load_groups(limit=limit, screen=screen)


def history_stats(screen=None):
    """מדדי-על להיסטוריה (מספר קבצים/גרסאות, שורות תקינות, אחוז הצלחה)."""
    import db as _db
    return _db.stats(screen=screen)

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
    enrich_columns(mapping, screen)
    return mapping


def load_field_spec(screen):
    """
    טוען מפרט שדות רשמי מ-specs/<SCREEN>.yaml (אם קיים).
    מחזיר dict {field_name: {max_length, required, type, decimals, boolean, readonly, title}}.
    """
    if screen in _SPEC_CACHE:
        return _SPEC_CACHE[screen]
    spec = {}
    path = os.path.join(SPECS_DIR, f"{screen}.yaml")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            spec = data.get("fields") or {}
        except yaml.YAMLError:
            spec = {}
    _SPEC_CACHE[screen] = spec
    return spec


def enrich_columns(mapping, screen):
    """
    מעשיר את עמודות המיפוי לפי מפרט השדות הרשמי (specs/<SCREEN>.yaml):
    ממלא אורך מקסימלי, חובה, טיפוס, דיוק עשרוני ובוליאני — לפי הגדרת השדה
    בפריוריטי — אלא אם הערך צוין במפורש במיפוי (ערך מפורש תמיד גובר).
    כך אין צורך לחזור על מגבלות השדה בכל מיפוי, והוולידציה תמיד תואמת לפריוריטי.
    """
    spec = load_field_spec(mapping.get("screen") or screen)
    if not spec:
        return
    for col in all_columns(mapping):
        fs = spec.get(col.get("target"))
        if not fs:
            continue
        if "max_length" not in col and fs.get("max_length") is not None:
            col["max_length"] = fs["max_length"]
        if "required" not in col and fs.get("required"):
            col["required"] = True
        if "type" not in col and fs.get("type"):
            col["type"] = fs["type"]
        if "decimals" not in col and fs.get("decimals") is not None:
            col["decimals"] = fs["decimals"]
        if fs.get("boolean"):
            col["boolean"] = True
        if fs.get("readonly"):
            col["_readonly"] = True
        if "title" not in col and fs.get("title"):
            col["title"] = fs["title"]      # שם השדה בעברית — לתצוגה למשתמש


def mapping_field_warnings(mapping, screen=None):
    """
    אזהרות ברמת המיפוי מול הקטלוג: שדה שאינו קיים בקטלוג, או שדה לקריאה בלבד.
    מוחזרות פעם אחת (לא לכל שורה) כדי לתפוס טעויות הגדרה מוקדם.
    """
    spec = load_field_spec(mapping.get("screen") or screen or "")
    if not spec:
        return []
    warns = []
    for col in mapping["columns"]:
        t = col.get("target")
        if col.get("source") is None and "value" not in col and col.get("default") is None:
            pass
        if col.get("_readonly"):
            warns.append(
                f"השדה '{t}' מוגדר בפריוריטי כלקריאה בלבד — בדרך כלל אין לטעון אליו ישירות."
            )
        elif t not in spec and not str(t).startswith(("XXXX", "Y_", "ERPG_")):
            warns.append(
                f"השדה '{t}' אינו מופיע בקטלוג השדות של המסך — ודא ששם השדה מדויק."
            )
    return warns


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


def subform_defs(mapping):
    """מחזיר את רשימת מסכי-המשנה (subforms) המוגדרים במיפוי (או ריק)."""
    return mapping.get("subforms") or []


def all_columns(mapping):
    """כל עמודות המיפוי — עמודות המסך הראשי + עמודות כל מסכי-המשנה."""
    cols = list(mapping["columns"])
    for sf in subform_defs(mapping):
        cols += sf.get("columns", [])
    return cols


def _key_columns(mapping):
    """אובייקטי העמודות של שדות המפתח, בסדר key_fields."""
    key_fields = mapping.get("key_fields") or []
    by_target = {c["target"]: c for c in mapping["columns"]}
    return [by_target[k] for k in key_fields if k in by_target]


def subform_mapping(mapping, subform):
    """
    בונה 'מיפוי' לקובץ מסך-משנה: שדות המפתח של האב + עמודות מסך-המשנה,
    כך שאפשר לייצר לו קובץ טעינה נפרד (מקושר לאב דרך המפתח).
    """
    vm = dict(mapping)
    vm["columns"] = _key_columns(mapping) + list(subform.get("columns", []))
    if subform.get("interface_name"):
        vm["interface_name"] = subform["interface_name"]
    return vm


def build_parent_records(valid_rows_out, mapping):
    """רשומות האב לקובץ הראשי — ייחודיות לפי key_fields (השורה הראשונה לכל מפתח)."""
    key_fields = mapping.get("key_fields") or []
    targets = [c["target"] for c in mapping["columns"]]
    seen, recs = set(), []
    for r in valid_rows_out:
        cm = {c["target"]: c["value"] for c in r["cells"]}
        if key_fields:
            key = tuple(cm.get(k, "") for k in key_fields)
            if key in seen:
                continue
            seen.add(key)
        recs.append({"values": [cm.get(t, "") for t in targets], "excel_row": r["excel_row"]})
    return recs


def build_subform_records(valid_rows_out, mapping, subform):
    """רשומות מסך-משנה — שורה לכל שורת קלט (שדות המפתח + עמודות מסך-המשנה)."""
    key_fields = mapping.get("key_fields") or []
    out_targets = key_fields + [c["target"] for c in subform.get("columns", [])]
    recs = []
    for r in valid_rows_out:
        cm = {c["target"]: c["value"] for c in r["cells"]}
        recs.append({"values": [cm.get(t, "") for t in out_targets], "excel_row": r["excel_row"]})
    return recs


def build_leveled_content(valid_records, mapping, order=None) -> str:
    """
    פורמט טעינה רב-רמתי בקובץ אחד (טעינת טופס בפריוריטי): כל שורה מתחילה במזהה
    רמה — 1 = רשומת אב (המסך הראשי), 2 = רשומת בן (מסך-המשנה הראשון), 3 = מסך-משנה
    שני, וכן הלאה. שורות הבן של אותו אב מקובצות מתחתיו לפי key_fields, בסדר ההופעה.

    valid_records: רשימת {"values": [...]} כאשר values מסודר לפי all_columns
    (עמודות האב ואחריהן עמודות מסכי-המשנה).
    order: סדר עמודות מבוקש (רשימת targets) — מיושם *בתוך כל רמה* בנפרד, כך
    שהמיישם יכול לסדר את השדות בשורת האב ובשורת הבן כרצונו.
    """
    delimiter = _DELIMITERS[mapping.get("delimiter", "tab")]
    all_cols = all_columns(mapping)
    n_parent = len(mapping["columns"])

    # לכל רמה: רשימת (value_index, column). ה-value_index הוא המיקום ב-values
    # (שווה למיקום ב-all_columns), ולכן סידור מחדש לפלט אינו משנה את מיקום הערך.
    levels = [("1", [(i, all_cols[i]) for i in range(n_parent)])]
    start = n_parent
    for i, sf in enumerate(subform_defs(mapping)):
        cols = sf.get("columns", [])
        levels.append((str(i + 2), [(start + j, cols[j]) for j in range(len(cols))]))
        start += len(cols)

    # סידור בתוך כל רמה לפי בקשת המשתמש — רק אם אין שמות target כפולים בין הרמות
    # (target כפול, למשל CODE באב ובבן, היה מתנגש בסידור לפי שם ומשבש את הפלט).
    all_targets = [c["target"] for _, entries in levels for _, c in entries]
    if order and len(set(all_targets)) == len(all_targets):
        pos = {t: k for k, t in enumerate(order)}
        for _, entries in levels:
            entries.sort(key=lambda e: pos.get(e[1]["target"], 10 ** 6))
    for lvl, entries in levels:                 # השמטת עמודות exclude
        entries[:] = [(vi, c) for vi, c in entries if not c.get("exclude")]

    parent_targets = [c["target"] for c in mapping["columns"]]
    key_fields = mapping.get("key_fields") or []
    key_idx = [parent_targets.index(k) for k in key_fields if k in parent_targets]

    order_keys, groups = [], {}
    for rec in valid_records:
        vals = rec["values"]
        key = tuple(vals[i] for i in key_idx) if key_idx else (len(order_keys),)
        if key not in groups:
            groups[key] = []
            order_keys.append(key)
        groups[key].append(vals)

    def _line(prefix, entries, vals):
        return delimiter.join([prefix] + [vals[vi] if vi < len(vals) else "" for vi, _ in entries])

    child_levels = levels[1:]
    lines = []
    for key in order_keys:
        rows = groups[key]
        lines.append(_line("1", levels[0][1], rows[0]))            # שורת האב
        for vals in rows:                                          # שורות הבן
            for level_no, entries in child_levels:
                lines.append(_line(level_no, entries, vals))
    content = "\r\n".join(lines)
    if lines:
        content += "\r\n"
    return content


def rows_from_dataframe(df, mapping, resolved):
    """הופך DataFrame לרשימת שורות {target: ערך_גולמי} לפי מיפוי העמודות."""
    columns = all_columns(mapping)
    rows = []
    for _, r in df.iterrows():
        row = {}
        for col in columns:
            actual = resolved.get(col["target"])
            row[col["target"]] = r[actual] if actual is not None else None
        rows.append(row)
    return rows


def _is_zero_amount(value):
    """True אם הערך ריק או שווה מספרית ל-0 (למשל '', '0', '0.00')."""
    s = str(value or "").strip()
    if s == "":
        return True
    try:
        return float(s.replace(",", "")) == 0
    except ValueError:
        return False


def _to_float(value):
    """מנסה להמיר ערך למספר (מסיר פסיקים/מטבע). מחזיר None אם לא ניתן."""
    try:
        s = str(value).replace(",", "").replace("₪", "").replace("$", "").strip()
        return float(s) if s not in ("", "-") else None
    except (ValueError, TypeError):
        return None


# שמות עמודות "נגזרות" שנוצרות בעיבוד המקדים (מקבלות עדיפות בזיהוי המיפוי)
DERIVED_AMOUNT_PRIMARY = "__AMOUNT_PRIMARY__"
DERIVED_DC = "__DC__"
DERIVED_AMOUNT_FX = "__AMOUNT_FX__"
DERIVED_ACCOUNT = "__ACCOUNT__"


def _excel_col_to_idx(ref):
    """ממיר אות עמודת אקסל (A,B,...,AA) לאינדקס 0-מבוסס, או None אם אינו אות."""
    s = str(ref).strip().upper()
    if not s.isalpha():
        return None
    idx = 0
    for ch in s:
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _resolve_col_ref(df, ref):
    """מזהה עמודה לפי אות אקסל (B) או לפי שם עמודה. מחזיר את שם העמודה או None."""
    idx = _excel_col_to_idx(ref)
    if idx is not None and 0 <= idx < len(df.columns):
        return df.columns[idx]
    if ref in df.columns:
        return ref
    return None


def _fmt_account(v):
    """מעצב מספר חשבון: 10001.0 -> '10001'; אחרת מחרוזת מנוקה."""
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


# עמודה משולבת: תא שמכיל תווית זכות/חובה (credit/debit) יחד עם מספר.
_CREDIT_KW = ("credit", "זכות")     # -> C
_DEBIT_KW = ("debit", "חובה")       # -> D
_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _dc_from_text(s):
    """מזהה C/D מטקסט חופשי: 'זכות'/'credit' -> C, 'חובה'/'debit' -> D.
    מחזיר '' אם אין תווית או שהיא דו-משמעית (גם וגם)."""
    low = str(s).lower()
    has_c = any(k in low for k in _CREDIT_KW)
    has_d = any(k in low for k in _DEBIT_KW)
    if has_c and not has_d:
        return "C"
    if has_d and not has_c:
        return "D"
    return ""


def _extract_number(s):
    """שולף את הערך המספרי הראשון ממחרוזת מעורבת (למשל 'זכות 1,200.50' -> 1200.5)."""
    m = _NUM_RE.search(str(s))
    return _to_float(m.group(0)) if m else None


def _cell_blank(v):
    """True אם התא ריק לכל דבר (None/רווחים/nan)."""
    return v is None or str(v).strip() == "" or str(v).strip().lower() == "nan"


def _mostly_numeric(series, frac=0.6):
    """True אם רוב התאים הלא-ריקים בעמודה הם מספרים (כדי לא לבלבל עמודת-סכום
    עם עמודת טקסט שבמקרה כותרתה מכילה credit/debit)."""
    vals = [v for v in series
            if not (v is None or str(v).strip() == "" or str(v).strip().lower() == "nan")]
    if not vals:
        return False
    numeric = sum(1 for v in vals if _extract_number(v) is not None)
    return numeric >= frac * len(vals)


def _dc_header_kind(col):
    """מסווג *כותרת* עמודה לפי המילה בשמה: 'Credit …'/'זכות' -> C,
    'Debit …'/'חובה' -> D. מחזיר None אם אין מילה כזו או ששתיהן מופיעות."""
    low = str(col).lower()
    is_c = any(k in low for k in _CREDIT_KW)
    is_d = any(k in low for k in _DEBIT_KW)
    if is_c and not is_d:
        return "C"
    if is_d and not is_c:
        return "D"
    return None


def _detect_combined_dc_col(df):
    """מאתר אוטומטית עמודה שבה התאים מכילים תווית זכות/חובה *וגם* מספר —
    מחזיר את שם העמודה עם הכי הרבה תאים כאלה (אם יש כמות מספקת), אחרת None."""
    best, best_n = None, 0
    for col in df.columns:
        if str(col).startswith("__"):        # דלג על עמודות נגזרות
            continue
        vals = [v for v in df[col]
                if not (v is None or str(v).strip() == "" or str(v).strip().lower() == "nan")]
        if len(vals) < 2:
            continue
        qual = sum(1 for v in vals if _dc_from_text(v) and _extract_number(v) is not None)
        if qual >= 2 and qual >= 0.5 * len(vals) and qual > best_n:
            best, best_n = col, qual
    return best


def preprocess_journal_df(df, mapping):
    """
    עיבוד מקדים ל-DataFrame לפני בניית הטבלה (מסכי יומן):
      • סינון שורות לא-רלוונטיות (min_row_values) — כותרות/יתרות עם מעט ערכים.
      • איחוד עמודות חובה/זכות נפרדות לעמודת סכום אחת + עמודת C/D.
      • עמודת סכום יחידה עם סימן -> C/D + ערך מוחלט (שלילי=C, חיובי=D).
    מחזיר DataFrame (חדש) עם עמודות נגזרות. אם אין הגדרות רלוונטיות — מחזיר כפי שהוא.
    """
    jc = mapping.get("journal") or {}
    min_vals = mapping.get("min_row_values")
    require = mapping.get("require_source") or []
    if not (jc.get("debit_source") or jc.get("credit_source") or jc.get("signed_source")
            or jc.get("fx_debit_source") or jc.get("fx_credit_source") or min_vals or require
            or jc.get("account_ffill") or jc.get("combined_source")
            or jc.get("combined_autodetect") or jc.get("dc_by_header")):
        return df

    df = df.copy()

    def _cell_empty(v):
        return v is None or str(v).strip() == "" or str(v).strip().lower() == "nan"

    # (1) העברת מס' חשבון מכותרת-המקטע לכל שורות התנועה שמתחתיה (ffill).
    # בכרטסת: מס' החשבון מופיע בעמודה B בשורת כותרת החשבון בלבד — נעביר אותו למטה.
    acc_ref = jc.get("account_ffill")
    if acc_ref is not None:
        acc_col = _resolve_col_ref(df, acc_ref)
        if acc_col is not None:
            accn = df[acc_col]
            acc_mask = accn.map(lambda v: not _cell_empty(v))
            ok = bool(acc_mask.any())
            by_t = {c["target"]: c for c in all_columns(mapping)}
            fcol = by_t.get("FNCNUM")
            if ok and fcol:
                fnames = [n for n in _source_aliases(fcol.get("source")) if n in df.columns]
                if fnames:
                    anc = df.apply(lambda r: any(not _cell_empty(r[n]) for n in fnames), axis=1)
                    # מבנה כרטסת: החשבון מופיע רק בשורות שאינן תנועה
                    ok = int((acc_mask & anc).sum()) == 0 and int((anc & ~acc_mask).sum()) > 0
            if ok:
                df[DERIVED_ACCOUNT] = accn.where(acc_mask).ffill().map(_fmt_account)

    # (1a) סינון שורות לא-רלוונטיות: חייבות ערך בעמודות-העוגן (למשל מס' תנועה).
    # שורות כותרת/יתרה בכרטסת חסרות מספר תנועה ולכן יסוננו.
    if require:
        by_target = {c["target"]: c for c in all_columns(mapping)}
        anchors = []
        for tgt in require:
            col = by_target.get(tgt)
            names = _source_aliases(col.get("source")) if col else []
            present = [n for n in names if n in df.columns]
            if present:
                anchors.append(present)
        if anchors:
            def _row_ok(r):
                return all(any(not _cell_empty(r[n]) for n in group) for group in anchors)
            df = df[df.apply(_row_ok, axis=1)].reset_index(drop=True)

    # (1b) סינון נוסף אופציונלי לפי כמות הערכים בשורה
    if min_vals:
        df = df[df.apply(lambda r: r.notna().sum() >= int(min_vals), axis=1)].reset_index(drop=True)

    def _present(names):
        return any(n in df.columns for n in (names or []))

    def _pick(row, names):
        for n in (names or []):
            if n in df.columns:
                v = row[n]
                if v is not None and str(v).strip() != "" and str(v).strip().lower() != "nan":
                    return v
        return None

    # (2) איחוד חובה/זכות (מטבע ראשי) -> סכום + C/D
    dsrc, csrc = jc.get("debit_source"), jc.get("credit_source")
    if _present(dsrc) or _present(csrc):
        amt, dc = [], []
        for _, row in df.iterrows():
            dv, cv = _pick(row, dsrc), _pick(row, csrc)
            if dv is not None:
                amt.append(abs(_to_float(dv)) if _to_float(dv) is not None else dv); dc.append("D")
            elif cv is not None:
                amt.append(abs(_to_float(cv)) if _to_float(cv) is not None else cv); dc.append("C")
            else:
                amt.append(""); dc.append("")
        df[DERIVED_AMOUNT_PRIMARY], df[DERIVED_DC] = amt, dc

    # (3) איחוד חובה/זכות מט"ח -> סכום מט"ח העסקה
    fdsrc, fcsrc = jc.get("fx_debit_source"), jc.get("fx_credit_source")
    if _present(fdsrc) or _present(fcsrc):
        famt = []
        for _, row in df.iterrows():
            v = _pick(row, fdsrc)
            if v is None:
                v = _pick(row, fcsrc)
            fv = _to_float(v)
            famt.append(abs(fv) if fv is not None else (v if v is not None else ""))
        df[DERIVED_AMOUNT_FX] = famt

    # (4) עמודת סכום יחידה עם סימן -> ערך מוחלט + C/D (שלילי=C, חיובי=D)
    ssrc = jc.get("signed_source")
    if _present(ssrc):
        amt, dc = [], []
        for _, row in df.iterrows():
            v = _pick(row, ssrc)
            n = _to_float(v)
            if n is None:
                amt.append(""); dc.append("")
            elif n == 0:
                amt.append("0"); dc.append("")          # 0 -> יטופל בכלל הש/מ
            else:
                amt.append(abs(n)); dc.append("C" if n < 0 else "D")
        df[DERIVED_AMOUNT_PRIMARY], df[DERIVED_DC] = amt, dc

    # (5) עמודה משולבת: תא עם תווית זכות/חובה (credit/debit) + מספר ->
    #     המספר (בערך מוחלט) לעמודת הסכום הראשי (SUM1), והתווית ל-C/D.
    #     מקור מפורש (combined_source) גובר; אחרת, אם combined_autodetect=true —
    #     מזוהה אוטומטית.
    csrc = jc.get("combined_source")
    ccol = next((n for n in (csrc or []) if n in df.columns), None)
    if ccol is None and jc.get("combined_autodetect"):
        ccol = _detect_combined_dc_col(df)
    if ccol is not None:
        amt, dc = [], []
        for _, row in df.iterrows():
            v = row[ccol]
            if _cell_empty(v):
                amt.append(""); dc.append("")
                continue
            num = _extract_number(v)
            amt.append(abs(num) if num is not None else "")
            dc.append(_dc_from_text(v))
        df[DERIVED_AMOUNT_PRIMARY], df[DERIVED_DC] = amt, dc

    # (6) עמודות חובה/זכות לפי *כותרת*: קובץ עם עמודות נפרדות שכותרתן מכילה
    #     Credit/Debit (או זכות/חובה) — לכל היותר אחת מהן מכילה מספר בשורה.
    #     הערך המספרי -> הסכום הראשי (SUM1); הצד (לפי הכותרת) -> C/D.
    #     dc_prefer (אופציונלי): כשיש כמה עמודות באותו צד (למשל "Entered"/
    #     "Accounted"), מעדיפים כותרת שמכילה מחרוזת זו לבחירת הסכום.
    if jc.get("dc_by_header"):
        prefer = str(jc.get("dc_prefer") or "").lower()

        def _amount_cols(kind):                      # עמודות-סכום של צד נתון (D/C)
            cols = [c for c in df.columns
                    if not str(c).startswith("__") and _dc_header_kind(c) == kind
                    and _mostly_numeric(df[c])]
            if prefer:                               # העדפת כותרת מסוימת (מטבע)
                cols.sort(key=lambda c: 0 if prefer in str(c).lower() else 1)
            return cols

        dcols, ccols = _amount_cols("D"), _amount_cols("C")
        if dcols or ccols:
            def _first_nonzero(row, cols):
                # הצד הלא-פעיל מגיע לעיתים כ-0 (ולא ריק) — לכן בוחרים את הערך
                # הראשון שאינו ריק *ואינו אפס*.
                for c in cols:
                    if _cell_empty(row[c]):
                        continue
                    n = _extract_number(row[c])
                    if n is not None and n != 0:
                        return n
                return None
            amt, dc = [], []
            for _, row in df.iterrows():
                dv = _first_nonzero(row, dcols)
                cv = _first_nonzero(row, ccols)
                if dv is not None:
                    amt.append(abs(dv)); dc.append("D")
                elif cv is not None:
                    amt.append(abs(cv)); dc.append("C")
                else:
                    amt.append(""); dc.append("")
            df[DERIVED_AMOUNT_PRIMARY], df[DERIVED_DC] = amt, dc

    return df


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
    columns = all_columns(mapping)
    date_format = mapping.get("date_format", DEFAULT_DATE_FORMAT)
    key_fields = mapping.get("key_fields") or []
    reserved_keys = reserved_keys or set()
    is_document = bool(subform_defs(mapping)) or bool(mapping.get("document"))

    # השלמה אוטומטית בין שדות: מעתיקים ערך משדה אחד לשני כשהיעד ריק
    # (למשל SUM2 -> SUM5). לא דורסים ערך שהמשתמש הזין ידנית.
    for rule in (mapping.get("copy_when_empty") or []):
        src, dst = rule.get("from"), rule.get("to")
        if not (src and dst):
            continue
        for row in input_rows:
            if _cell_blank(row.get(dst)) and not _cell_blank(row.get(src)):
                row[dst] = row.get(src)

    rows_out = []
    for i, row in enumerate(input_rows):
        cells = []
        row_valid = True
        for col in columns:
            if col.get("generate") == "rownum":  # מספור שורות רץ אוטומטי
                cells.append({"target": col["target"], "value": str(i + 1),
                              "error": None, "warning": None})
                continue
            value, err = process_value(row.get(col["target"]), col, date_format)
            if not err:
                err = validators.validate_cell(value, col)
            # בדיקת פורמט (טלפון/דוא"ל וכו') — כברירת מחדל אזהרה, לא פסילה
            warning = None
            fmt = validators.validate_format(value, col)
            if fmt:
                msg, severity = fmt
                if severity == "error" and not err:
                    err = msg
                elif severity != "error":
                    warning = msg
            if warning is None:
                warning = lookup_warning(col, value)
            if err:
                row_valid = False
            cells.append({"target": col["target"], "value": value,
                          "error": err, "warning": warning})
        # כלל: אם כל עמודות-הסכום המוגדרות הן 0/ריק — השורה לא תיטען לקובץ
        zcols = mapping.get("exclude_if_all_zero")
        if zcols:
            cmap = {c["target"]: c["value"] for c in cells}
            if all(_is_zero_amount(cmap.get(t, "")) for t in zcols):
                row_valid = False
                for c in cells:
                    if c["target"] in zcols and not c["error"]:
                        c["error"] = "כל הסכומים 0 — השורה לא תיטען לקובץ"
                        break

        excel_row = excel_rows[i] if excel_rows else i + 2
        rows_out.append({"excel_row": excel_row, "cells": cells, "valid": row_valid})

    # בדיקת כפילויות — במסמך (עם מסכי-משנה) המפתח חוזר בכל שורת בת, לכן לא נפסל
    if key_fields and not is_document:
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
    """כל שמות עמודות המקור (כולל כינויים) — לצורך זיהוי אוטומטי של שורת הכותרת."""
    names = []
    for c in all_columns(mapping):
        names.extend(_source_aliases(c.get("source")))
    return names


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
    resolved = build_column_lookup(df, all_columns(mapping))

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

    for i, col in enumerate(all_columns(mapping), start=1):
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


def _finalize_raw(raw, header_row, expected_sources, name):
    """מ-DataFrame גולמי (ללא כותרת) -> DataFrame עם כותרות מזוהות ושורות נתונים."""
    if raw.empty:
        raise UserError(f"{name} ריק — אין שורות לעיבוד.")
    if header_row is not None:
        hidx = int(header_row) - 1
        if hidx < 0 or hidx >= len(raw):
            raise UserError(
                f"שורת הכותרת שצוינה ({header_row}) מחוץ לטווח הקובץ (יש {len(raw)} שורות)."
            )
    else:
        hidx = detect_header_row(raw, expected_sources)

    columns = _build_unique_headers(raw.iloc[hidx].tolist())
    df = raw.iloc[hidx + 1:].copy()
    df.columns = columns
    df = df.dropna(how="all").reset_index(drop=True)  # מסירים שורות ריקות לגמרי
    if df.empty:
        raise UserError(f"לא נמצאו שורות נתונים מתחת לשורת הכותרת (שורה {hidx + 1}) ב{name}.")
    return df


def _read_delimited_raw(source, name):
    """קורא קובץ טקסט מופרד (.txt/.dat/.csv/.tsv). מזהה קידוד ומפריד אוטומטית."""
    import csv
    import io as _io
    data = open(source, "rb").read() if isinstance(source, str) else source.read()
    text = None
    for enc in ("cp1255", "utf-8-sig", "utf-8"):  # פריוריטי און-פרם בד"כ windows-1255
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = data.decode("cp1255", errors="replace")
    sample = "\n".join(text.splitlines()[:20])
    delim = "\t"
    try:  # ניחוש מפריד (טאב / פסיק / נקודה-פסיק / pipe)
        delim = csv.Sniffer().sniff(sample, delimiters="\t,;|").delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in ("\t", "|", ";", ",")}
        delim = max(counts, key=counts.get) if any(counts.values()) else "\t"
    return pd.read_csv(_io.StringIO(text), sep=delim, header=None, dtype=object,
                       engine="python", keep_default_na=True)


def _source_bytes(source):
    """מחזיר את בייטי המקור (נתיב או file-like), עם החזרת המצביע להתחלה."""
    if isinstance(source, str):
        with open(source, "rb") as f:
            return f.read()
    try:
        source.seek(0)
    except (AttributeError, OSError):
        pass
    return source.read()


_MIN_XLSX_STYLES = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    b'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    b'<fonts count="1"><font/></fonts>'
    b'<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
    b'<borders count="1"><border/></borders>'
    b'<cellStyleXfs count="1"><xf/></cellStyleXfs>'
    b'<cellXfs count="1"><xf/></cellXfs></styleSheet>'
)


def _strip_xlsx_styles(data):
    """מחליף styles.xml פגום ב-xlsx בסגנון מינימלי תקין — כדי לאפשר קריאה."""
    import io as _io
    import zipfile
    out = _io.BytesIO()
    with zipfile.ZipFile(_io.BytesIO(data)) as zin, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.namelist():
            b = zin.read(item)
            if item.endswith("styles.xml"):
                b = _MIN_XLSX_STYLES
            zout.writestr(item, b)
    out.seek(0)
    return out


def _read_xlsx(source, sheet):
    """קורא xlsx; אם קובץ הסגנונות פגום (שגיאת openpyxl) — קורא שוב ללא הסגנונות."""
    import io as _io
    import warnings
    sn = sheet if sheet is not None else 0
    try:
        return pd.read_excel(source, sheet_name=sn, header=None, dtype=object, engine="openpyxl")
    except ValueError:
        raise
    except Exception:  # noqa: BLE001 — כנראה stylesheet פגום; ננסה לתקן ולקרוא שוב
        data = _source_bytes(source)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return pd.read_excel(_strip_xlsx_styles(data), sheet_name=sn,
                                 header=None, dtype=object, engine="openpyxl")


def read_input(source, sheet=None, header_row=None, expected_sources=None, filename=None):
    """
    קורא קובץ קלט לפי הסוג: xlsx / txt / dat / csv / tsv.
    source — נתיב או file-like. filename — לזיהוי הסוג כשמדובר ב-file-like.
    שורת הכותרת מזוהה אוטומטית (או header_row מפורש).
    """
    name = filename or (source if isinstance(source, str) else "הקובץ שהועלה")
    if isinstance(source, str) and not os.path.exists(source):
        raise UserError(f"קובץ הקלט לא נמצא: {source}")
    ext = os.path.splitext(str(name))[1].lower().lstrip(".")

    if ext in ("xlsx", "xlsm", "xls", ""):
        try:
            raw = _read_xlsx(source, sheet)
        except ValueError as e:
            raise UserError(f"לא ניתן לקרוא את הגיליון '{sheet}' מ{name}.\n{e}")
        except Exception as e:  # noqa: BLE001
            raise UserError(f"שגיאה בקריאת קובץ האקסל ({name}):\n{e}")
    elif ext in ("txt", "dat", "csv", "tsv"):
        try:
            raw = _read_delimited_raw(source, name)
        except Exception as e:  # noqa: BLE001
            raise UserError(f"שגיאה בקריאת קובץ הטקסט ({name}):\n{e}")
    else:
        raise UserError(
            f"סוג קובץ לא נתמך: '.{ext}'. סוגים נתמכים: xlsx, txt, dat, csv."
        )
    return _finalize_raw(raw, header_row, expected_sources, name)


# תאימות לאחור — הקוד הקיים קורא ל-read_excel
def read_excel(source, sheet=None, header_row=None, expected_sources=None):
    return read_input(source, sheet, header_row, expected_sources)


def _source_aliases(source):
    """מחזיר את שמות המקור האפשריים לעמודה (source יכול להיות שם בודד או רשימת כינויים)."""
    if source is None:
        return []
    return list(source) if isinstance(source, (list, tuple)) else [source]


def resolve_columns(df, columns, overrides=None):
    """
    פותר לכל עמודת מיפוי איזו עמודה באקסל מזינה אותה.
    - source יכול להיות שם בודד או רשימת כינויים (aliases) — נבחר הכינוי הראשון
      שקיים בקובץ.
    - overrides: {target: שם_עמודה_באקסל} — בחירה ידנית של המשתמש (גוברת על הזיהוי
      האוטומטי). ערך ריק = "לא ממופה" במפורש.

    מחזיר (resolved, unmatched_required, unmatched_optional) — בלי לזרוק שגיאה,
    כדי שהממשק יוכל להציג טבלה ולתת למשתמש לבחור עמודה לשדות שלא זוהו.
    """
    overrides = overrides or {}
    valid_cols = set(df.columns)
    lookup = {_norm_header(c): c for c in df.columns}
    resolved, unmatched_required, unmatched_optional = {}, [], []
    for col in columns:
        t = col["target"]
        aliases = _source_aliases(col.get("source"))
        if not aliases:
            continue  # עמודת ערך קבוע — אין מקור
        required_missing = col.get("required") and col.get("default") in (None, "")
        if t in overrides:  # בחירה ידנית מהממשק
            val = overrides[t]
            if val and val in valid_cols:
                resolved[t] = val
            elif required_missing:
                unmatched_required.append(t)
            else:
                unmatched_optional.append(t)
            continue
        actual = next((lookup[_norm_header(a)] for a in aliases if _norm_header(a) in lookup), None)
        if actual is not None:
            resolved[t] = actual
        elif required_missing:
            unmatched_required.append(t)
        else:
            unmatched_optional.append(t)
    return resolved, unmatched_required, unmatched_optional


def build_column_lookup(df, columns):
    """
    עטיפה ל-resolve_columns עבור ה-CLI (לא אינטראקטיבי): זורקת שגיאה ברורה
    אם שדה חובה לא זוהה. בממשק הוובי משתמשים ב-resolve_columns ישירות.
    """
    resolved, req, _ = resolve_columns(df, columns)
    if req:
        amap = {c["target"]: _source_aliases(c.get("source")) for c in columns}
        lines = "\n  - ".join(f"{t} (חיפשנו: {', '.join(amap.get(t, []))})" for t in req)
        raise UserError(
            "שדות חובה שלא נמצאה להם עמודה מתאימה בקובץ האקסל:\n  - " + lines
            + "\n\nעמודות שקיימות בקובץ: "
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
    # עמודה ידנית (המיישם מקליד בטבלה) — משמרים את הערך שהוקלד, לא ברירת מחדל
    if column.get("manual"):
        return transforms.auto_clean(raw), None

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
        # שדה טלפון (format: phone) — משאירים ספרות בלבד ("צריך להיות רק מספר")
        if column.get("format") == "phone" and value != "":
            value = transforms.NAMED_TRANSFORMS["digits_only"](value)

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

    # התאמת ערך לפי טבלת lookup (מטבעות / קודי תשלום וכו') — קוד/תיאור -> קוד
    lk = column.get("lookup")
    if lk and value != "":
        code = lookup_value(lk, value)
        if code:
            value = code

    return value, None


def lookup_warning(column, value):
    """אזהרה אם ערך של עמודת lookup לא נמצא בטבלה (לא הותאם לקוד)."""
    lk = column.get("lookup")
    if not lk or value == "":
        return None
    if _norm_header(value) not in load_lookup(lk):
        return f"ערך לא נמצא בטבלת '{lk}': '{value}'"
    return None


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
    main_targets = {c["target"] for c in mapping["columns"]}
    columns = all_columns(mapping)  # כולל עמודות מסכי-משנה (לוולידציה + row_dict)
    date_format = mapping.get("date_format", DEFAULT_DATE_FORMAT)

    records = []
    for pos, (_, row) in enumerate(df.iterrows()):
        excel_row = pos + 2  # שורה 1 = כותרות, הנתונים מתחילים בשורה 2
        values = []
        row_dict = {}
        reason = None
        warnings = []

        for col in columns:
            if col.get("generate") == "rownum":  # מספור שורות רץ אוטומטי
                v = str(pos + 1)
                if col["target"] in main_targets:
                    values.append(v)
                row_dict[col["target"]] = v
                continue
            actual = resolved.get(col["target"])
            raw = row[actual] if actual is not None else None

            value, err = process_value(raw, col, date_format)

            if reason is None:
                e = err or validators.validate_cell(value, col)
                if e:
                    reason = e

            fmt = validators.validate_format(value, col)
            if fmt:
                msg, severity = fmt
                if severity == "error" and reason is None:
                    reason = msg
                elif severity != "error":
                    warnings.append(msg)
            lw = lookup_warning(col, value)
            if lw:
                warnings.append(lw)

            # 'values' = עמודות המסך הראשי בלבד (סדר הפלט); row_dict = כל השדות
            if col["target"] in main_targets:
                values.append(value)
            row_dict[col["target"]] = value

        records.append(
            {
                "excel_row": excel_row,
                "values": values,
                "row_dict": row_dict,
                "reason": reason,
                "warnings": warnings,
                "original": row,
            }
        )

    # בדיקת כפילויות על השורות שעברו ולידציית תא (reason ריק)
    # במסמך (מסכי-משנה) המפתח חוזר בכל שורת בת — לכן לא בודקים כפילות
    if not (subform_defs(mapping) or mapping.get("document")):
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
def reorder_for_export(valid_records, mapping, order_targets, hidden_targets=None):
    """
    מסדר מחדש את העמודות לפי סדר מבוקש (order_targets — רשימת שמות target).
    מחזיר (רשומות_מסודרות, מיפוי_מסודר) כך שגם קובץ הטעינה וגם שורת הכותרת
    (אם include_header) יֵצאו בסדר הזה. עמודות שלא צוינו נוספות בסוף.
    hidden_targets: עמודות שהמשתמש הסתיר — יוסרו לגמרי מהייצוא.
    """
    columns = mapping["columns"]
    tmap = {c["target"]: i for i, c in enumerate(columns)}
    hidden = {t for t in (hidden_targets or []) if t in tmap}
    order = [t for t in (order_targets or []) if t in tmap and t not in hidden]
    # השלמת חוסרים (למעט מוסתרות)
    order += [c["target"] for c in columns
              if c["target"] not in order and c["target"] not in hidden]
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
    # עמודות עם exclude:true מוצגות בטבלה אך אינן נכתבות לקובץ (למשל הערות למיישם)
    keep = [i for i, c in enumerate(columns) if not c.get("exclude")]

    lines = []
    if include_header:
        lines.append(delimiter.join(columns[i]["target"] for i in keep))
    for rec in valid_records:
        vals = rec["values"]
        lines.append(delimiter.join(vals[i] for i in keep if i < len(vals)))

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


def _write_records_file(records, mp, path):
    with open(path, "wb") as f:
        f.write(load_content_bytes(build_load_content(records, mp), mp))


def _write_document_files(valid_records, mapping, screen):
    """
    כותב קבצי מסמך: קובץ אב (ייחודי לפי מפתח) + קובץ לכל מסך-משנה.
    valid_records — רשומות ה-CLI (עם row_dict של כל השדות).
    מחזיר (parent_path, [sub_paths]).
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ext = load_file_extension(mapping)
    key_fields = mapping.get("key_fields") or []
    main_targets = [c["target"] for c in mapping["columns"]]

    # אב — ייחודי לפי מפתח
    seen, parent = set(), []
    for r in valid_records:
        rd = r["row_dict"]
        key = tuple(rd.get(k, "") for k in key_fields)
        if key_fields:
            if key in seen:
                continue
            seen.add(key)
        parent.append({"values": [rd.get(t, "") for t in main_targets]})
    parent_path = os.path.join(OUTPUT_DIR, f"{screen}_load.{ext}")
    _write_records_file(parent, mapping, parent_path)

    # מסכי-משנה — שורה לכל שורת קלט
    sub_paths = []
    for sf in subform_defs(mapping):
        vm = subform_mapping(mapping, sf)
        out_targets = key_fields + [c["target"] for c in sf.get("columns", [])]
        subrecs = [{"values": [r["row_dict"].get(t, "") for t in out_targets]} for r in valid_records]
        sub_path = os.path.join(OUTPUT_DIR, f"{screen}_{sf['name']}_load.{load_file_extension(vm)}")
        _write_records_file(subrecs, vm, sub_path)
        sub_paths.append(sub_path)

    return parent_path, sub_paths


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
    resolved = build_column_lookup(df, all_columns(mapping))

    records = process_rows(df, mapping, resolved)
    valid_records = [r for r in records if r["reason"] is None]
    rejected_records = [r for r in records if r["reason"] is not None]

    enc_warnings = check_encoding(
        valid_records, mapping["columns"], mapping.get("encoding", "windows-1255")
    )
    # אזהרות נתונים (למשל טלפון/דוא"ל לא תקין) — לא פוסלות, רק מתריעות
    data_warnings = [
        f"שורה {r['excel_row']}: {w}" for r in records for w in r.get("warnings", [])
    ]
    # אזהרות מיפוי מול קטלוג השדות (שדה לא מוכר / לקריאה בלבד)
    map_warnings = mapping_field_warnings(mapping, args.screen)
    enc_warnings = map_warnings + enc_warnings + data_warnings

    out_path = None
    rejected_path = None
    extra_paths = []

    if not args.dry_run and valid_records:
        if subform_defs(mapping):
            out_path, extra_paths = _write_document_files(valid_records, mapping, args.screen)
        else:
            out_path = write_load_file(valid_records, mapping, args.screen)

    if rejected_records:
        rejected_path = write_rejected_file(rejected_records, df, args.screen)

    report = build_report(
        args.screen, mapping, len(records), valid_records, rejected_records,
        enc_warnings, out_path, rejected_path, args.dry_run,
    )
    report_path = write_report_file(report, enc_warnings, args.screen)

    print(report)
    if extra_paths:
        print("  קבצי מסך-משנה:")
        for p in extra_paths:
            print(f"    {p}")
    print(f"\nהדוח נשמר: {report_path}")

    append_history({
        "screen": args.screen, "source": os.path.basename(str(args.input)),
        "total": len(records), "valid": len(valid_records),
        "invalid": len(rejected_records), "warnings": len(enc_warnings),
        "via": "cli", "dry_run": bool(args.dry_run),
    })

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
