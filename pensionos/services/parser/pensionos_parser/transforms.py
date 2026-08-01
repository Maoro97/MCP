"""נרמול ערכים — שלב 5 בצנרת.

כל טרנספורם מחזיר `(value, fixes, issue_hint)`. הוא לעולם לא זורק חריגה על
נתון פגום: הוא מחזיר None ורמז לחריג, וההחלטה מה לעשות עם זה שייכת למדיניות
השדה (`on_missing` / `range`) ולא לטרנספורם.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .issues import Code

# --- תאריכים ------------------------------------------------------------
# יצרנים שונים מדווחים בפורמטים שונים, ולעיתים אותו יצרן משנה פורמט
# בין שדות באותו קובץ.
_DATE_FORMATS = (
    "%Y%m%d",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d.%m.%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%Y%m",  # חודש בלבד — נרמול ליום הראשון
)
_DATE_MIN = date(1900, 1, 1)

# ערכי "אין תאריך" שמדווחים כמספר במקום כתג ריק
_NULL_DATES = {"00000000", "0", "99999999", "19000101", "18991230"}

# --- מספרים -------------------------------------------------------------
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")
_TRAILING_MINUS = re.compile(r"^\s*(?P<num>[\d.,]+)\s*-\s*$")
_NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")


@dataclass
class Value:
    """תוצאת נרמול של שדה בודד."""

    value: Any = None
    raw: str | None = None
    fixes: list[str] = field(default_factory=list)
    hint: Code | None = None
    confidence: float = 1.0


def as_string(raw: str | None) -> Value:
    if raw is None:
        return Value(raw=raw)
    cleaned = " ".join(raw.split())  # רווחים כפולים/טאבים מקבצים ידניים
    fixes = ["whitespace_collapsed"] if cleaned != raw else []
    return Value(value=cleaned or None, raw=raw, fixes=fixes)


def as_decimal(raw: str | None, *, allow_zero: bool = True) -> Value:
    """מספר עשרוני עם כל הסטיות שראינו בשטח."""
    if raw is None:
        return Value(raw=raw)
    txt = raw.strip()
    fixes: list[str] = []

    if not txt:
        return Value(raw=raw)

    # מינוס עוקב: "1,234.50-" — מורשת של מערכות mainframe
    if m := _TRAILING_MINUS.match(txt):
        txt = "-" + m.group("num")
        fixes.append("trailing_minus")

    # מפריד אלפים
    if _THOUSANDS.search(txt):
        txt = _THOUSANDS.sub("", txt)
        fixes.append("thousands_separator")

    # פסיק כנקודה עשרונית: "0,22"
    if "," in txt and "." not in txt:
        txt = txt.replace(",", ".")
        fixes.append("comma_decimal_point")

    txt = txt.replace("₪", "").replace("%", "").replace(" ", "").strip()

    if not _NUMERIC.match(txt):
        return Value(raw=raw, hint=Code.BAD_FORMAT)

    num = float(txt)
    if num == 0 and not allow_zero:
        # "0" שמשמעו "לא ידוע" — התקלה שגורמת למערכות הקיימות להציג
        # דמי ניהול 0% ולהטעות את הסוכן.
        return Value(raw=raw, hint=Code.MISSING_FIELD, fixes=fixes + ["zero_as_null"])
    return Value(value=num, raw=raw, fixes=fixes)


def as_int(raw: str | None) -> Value:
    v = as_decimal(raw)
    if v.value is None:
        return v
    v.value = int(v.value)
    return v


def as_percent(
    raw: str | None, *, fraction_threshold: float = 0.0, allow_zero: bool = True
) -> Value:
    """נרמול אחוזים ליחידה אחת: 'אחוז עשרוני'.

    יצרן א' מדווח `0.5`, יצרן ב' `0.005`, יצרן ג' `"0.50%"` — כולם מתכוונים
    לחצי אחוז. כשהערך נופל מתחת ל-`fraction_threshold` הוא כנראה שבר עשרוני,
    אבל זו היוריסטיקה ולא ודאות — ולכן מסומן כחריג לבדיקה אנושית ולא
    "מתוקן" בשקט.
    """
    if raw is None:
        return Value(raw=raw)
    had_sign = "%" in raw
    v = as_decimal(raw, allow_zero=allow_zero)
    if v.value is None:
        return v
    if had_sign:
        v.fixes.append("percent_sign_stripped")
        return v
    if fraction_threshold and 0 < v.value < fraction_threshold:
        v.value = round(v.value * 100, 6)
        v.fixes.append("fraction_to_percent")
        v.hint = Code.AMBIGUOUS_PERCENT
        v.confidence = 0.75
    return v


def as_date(raw: str | None) -> Value:
    if raw is None:
        return Value(raw=raw)
    txt = raw.strip()
    if not txt or txt in _NULL_DATES:
        return Value(raw=raw)

    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(txt, fmt).date()
        except ValueError:
            continue
        # שפיות: תאריך מחוץ לטווח סביר מעיד על פורמט שפוענח לא נכון
        if not (_DATE_MIN <= parsed <= date.today().replace(year=date.today().year + 1)):
            return Value(raw=raw, hint=Code.OUT_OF_RANGE)
        fixes = [f"date_format:{fmt}"] if fmt != "%Y%m%d" else []
        return Value(value=parsed, raw=raw, fixes=fixes)

    return Value(raw=raw, hint=Code.BAD_FORMAT)


def as_bool(raw: str | None) -> Value:
    if raw is None:
        return Value(raw=raw)
    txt = raw.strip().lower()
    if txt in {"1", "true", "y", "yes", "כן"}:
        return Value(value=True, raw=raw)
    if txt in {"0", "false", "n", "no", "לא"}:
        return Value(value=False, raw=raw)
    return Value(raw=raw, hint=Code.BAD_FORMAT)


def as_code(raw: str | None, table: dict[str, str], default: str | None = None) -> Value:
    """תרגום קוד יצרן לערך קנוני.

    קוד לא מוכר לעולם לא מומר בניחוש — הוא מקבל את ערך ברירת המחדל
    ומסומן כחריג, כי ניחוש סוג מוצר עלול לגרור המלצה שגויה.
    """
    if raw is None:
        return Value(raw=raw)
    key = raw.strip()
    if key in table:
        return Value(value=table[key], raw=raw)
    return Value(value=default, raw=raw, hint=Code.UNKNOWN_CODE_VALUE, confidence=0.0)


# --- ת"ז ---------------------------------------------------------------


def normalize_national_id(raw: str | None) -> str | None:
    """ריפוד ל-9 ספרות. ת"ז ישראלית מדווחת לעיתים ללא אפסים מובילים."""
    if raw is None:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits or len(digits) > 9:
        return None
    return digits.zfill(9)


def is_valid_national_id(value: str | None) -> bool:
    """ספרת ביקורת לפי אלגוריתם ת"ז ישראלי (Luhn מותאם)."""
    normalized = normalize_national_id(value)
    if normalized is None or len(normalized) != 9:
        return False
    total = 0
    for i, ch in enumerate(normalized):
        digit = int(ch) * (1 if i % 2 == 0 else 2)
        total += digit if digit < 10 else digit - 9
    return total % 10 == 0


TRANSFORMS = {
    "string": as_string,
    "decimal": as_decimal,
    "int": as_int,
    "percent": as_percent,
    "date": as_date,
    "bool": as_bool,
}
