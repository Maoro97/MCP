# -*- coding: utf-8 -*-
"""
journal.py — מנוע הסבת תנועות יומן (ליבה חשבונאית)

פונקציות טהורות לעיבוד תנועות יומן, בהתאם לכללי ההסבה:
- סכום ראשי בעמודה אחת: מינוס -> C, פלוס -> D, והסכום בערך מוחלט.
  אם קיימת עמודת "חובה/זכות" — הסימן נקבע לפיה (חובה=D, זכות=C).
- קיבוץ שורות לתנועה לפי "מספר תנועת יומן".
- בדיקת איזון תנועה במטבע ראשי ובמטבע משני, וחישוב הסכום החסר לאיזון.
- איזון אוטומטי: אם ההפרש קטן מסף מוגדר — משלימים אותו לאחת השורות מאותו סימן.

המנוע אינו תלוי בממשק — הוא מקבל שורות כ-dict {target: value} ופרטי תפקידים
(איזו עמודה היא הסכום, הסימן, מספר התנועה וכו').
"""

from collections import OrderedDict


def to_number(value):
    """ממיר מחרוזת למספר (float). ריק/לא-מספרי -> None."""
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("₪", "").replace(" ", "")
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _fmt(n):
    """מחזיר מספר כמחרוזת נקייה (בלי .0 מיותר)."""
    if n is None:
        return ""
    if float(n).is_integer():
        return str(int(round(n)))
    return ("%f" % n).rstrip("0").rstrip(".")


def dc_from_indicator(text):
    """מיפוי ערך עמודת חובה/זכות לסימן C/D. חובה=D, זכות=C."""
    t = str(text or "").strip()
    if t in ("חובה", "D", "d", "דביט", "debit"):
        return "D"
    if t in ("זכות", "C", "c", "קרדיט", "credit"):
        return "C"
    return ""


def split_amount(amount_value, dc_indicator=None):
    """
    מפרק סכום ראשי לערך מוחלט + סימן C/D.
    - אם dc_indicator ניתן (עמודת חובה/זכות): הסימן נקבע לפיה.
    - אחרת: לפי סימן הסכום — שלילי=C, חיובי=D.
    מחזיר (abs_amount_str, 'C'/'D'/'').
    """
    n = to_number(amount_value)
    if dc_indicator is not None and str(dc_indicator).strip() != "":
        dc = dc_from_indicator(dc_indicator)
        return (_fmt(abs(n)) if n is not None else ""), dc
    if n is None:
        return "", ""
    dc = "C" if n < 0 else "D"
    return _fmt(abs(n)), dc


def signed_amount(abs_value, dc):
    """מחזיר ערך מסומן: D חיובי, C שלילי (לחישוב איזון)."""
    n = to_number(abs_value)
    if n is None:
        return 0.0
    n = abs(n)
    return -n if dc == "C" else n


def group_by_txn(rows, txn_target):
    """
    מקבץ אינדקסי שורות לפי מספר תנועת יומן.
    מחזיר OrderedDict: {txn_value: [row_index, ...]} (שומר על הסדר).
    שורות ללא מספר תנועה מקובצות תחת מפתח ריק ("").
    """
    groups = OrderedDict()
    for i, row in enumerate(rows):
        key = str(row.get(txn_target, "") or "").strip()
        groups.setdefault(key, []).append(i)
    return groups


def transaction_balance(rows, indices, amount_target, dc_target, tol=0.005):
    """
    מחשב איזון תנועה: סכום מסומן של כל שורות התנועה.
    מחזיר dict: {debit, credit, diff, balanced}.
    diff = סה"כ חובה (D) מינוס סה"כ זכות (C). balanced אם |diff| <= tol.
    """
    debit = credit = 0.0
    for i in indices:
        dc = str(rows[i].get(dc_target, "") or "").strip().upper()
        amt = to_number(rows[i].get(amount_target))
        if amt is None:
            continue
        amt = abs(amt)
        if dc == "D":
            debit += amt
        elif dc == "C":
            credit += amt
    diff = round(debit - credit, 2)
    return {"debit": round(debit, 2), "credit": round(credit, 2),
            "diff": diff, "balanced": abs(diff) <= tol}


def auto_balance(rows, indices, amount_target, dc_target, max_diff, tol=0.005):
    """
    איזון אוטומטי לתנועה: אם ההפרש קטן/שווה ל-max_diff, מוסיף את ההפרש
    לאחת השורות מאותו סימן שצריך חיזוק, ומחזיר (fixed_row_index, added) או (None, 0).
    - אם diff>0 (עודף חובה) -> מוסיפים לצד זכות (C).
    - אם diff<0 (עודף זכות) -> מוסיפים לצד חובה (D).
    """
    bal = transaction_balance(rows, indices, amount_target, dc_target, tol)
    if bal["balanced"]:
        return None, 0.0
    diff = bal["diff"]
    if abs(diff) > max_diff + tol:
        return None, 0.0
    need_side = "C" if diff > 0 else "D"  # לאיזה צד להוסיף
    add = abs(diff)
    for i in indices:
        dc = str(rows[i].get(dc_target, "") or "").strip().upper()
        if dc == need_side:
            cur = to_number(rows[i].get(amount_target)) or 0.0
            rows[i][amount_target] = _fmt(abs(cur) + add)
            return i, add
    return None, 0.0


def convert_secondary_by_rate(primary_amount, rate):
    """סכום במטבע משני = סכום ראשי × שער. מחזיר מחרוזת (2 ספרות) או ''."""
    a = to_number(primary_amount)
    r = to_number(rate)
    if a is None or r is None or r == 0:
        return ""
    return "%.2f" % (abs(a) * r)
