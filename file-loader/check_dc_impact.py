# -*- coding: utf-8 -*-
"""
מדידה לפני אכיפת "חובה/זכות הוא שדה חובה" — קריאה בלבד, לא משנה שום קובץ.

למה: ההחלטה ש"חובה/זכות ריק = שגיאה" תפסול שורות שנטענות היום. שורה שגויה אינה
נכנסת לקובץ הטעינה אלא ל-<SCREEN>_rejected.xlsx. הסקריפט הזה סופר, על קובץ אמיתי
ועם המיפוי *הקיים*, כמה שורות ייפסלו מעתה — לפני שמשנים משהו.

שימוש:
    python check_dc_impact.py <קובץ.xlsx> [שם-גיליון]

מה חשוב במספרים:
  «שורות שייפסלו מעתה» — אם הוא לא קרוב לאפס, לעצור ולדון לפני האכיפה.
  «ערכים שאינם D/C»     — כל ערך חוזר שם הוא מועמד להוספה ל-value_map במיפוי.
"""
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# לא נוגעים בתיקיית הפלט האמיתית
os.environ.setdefault("FILE_LOADER_OUTPUT", os.path.join(HERE, "output", "_dc_check"))

import main as core  # noqa: E402

SCREEN = "JOURNAL"
AMOUNTS = ("SUM1", "SUM2", "SUM5")


def cell(row, target):
    return next((c["value"] for c in row["cells"] if c["target"] == target), "")


def main(path, sheet=None):
    mapping = core.load_mapping(SCREEN)
    jc = mapping.get("journal") or {}
    dc_target = jc.get("dc") or "DEBIT"
    zcols = [t for t in (mapping.get("exclude_if_all_zero") or []) if t] or list(AMOUNTS)

    with open(path, "rb") as fh:
        df = core.read_input(fh, sheet, filename=path,
                             header_row=mapping.get("header_row"),
                             expected_sources=core._expected_sources(mapping))
    print("עמודות שזוהו בקובץ: %d" % len(df.columns))

    # אותו מסלול בדיוק כמו _build_grid ב-webapp.py
    df = core.preprocess_journal_df(df, mapping)
    resolved, req_missing, _opt = core.resolve_columns(df, core.all_columns(mapping))
    rows = core.evaluate_grid(mapping, core.rows_from_dataframe(df, mapping, resolved))

    blank, junk, allzero_blank = [], [], []
    junk_values = Counter()
    for r in rows:
        v = str(cell(r, dc_target) or "").strip()
        if v == "":
            blank.append(r)
            if all(core._is_zero_amount(cell(r, t)) for t in zcols):
                allzero_blank.append(r)
        elif v.upper() not in ("D", "C"):
            junk.append(r)
            junk_values[v] += 1

    new_rejects = len(blank) - len(allzero_blank)

    print()
    print("סך השורות שנקלטו            : %d" % len(rows))
    print("שורות שגויות כבר היום        : %d" % sum(1 for r in rows if not r["valid"]))
    print("-" * 52)
    print("חובה/זכות ריק                : %d" % len(blank))
    print("  מהן כבר נפסלות (כל הסכומים 0): %d" % len(allzero_blank))
    print("  >>> שורות שייפסלו מעתה     : %d" % new_rejects)
    print("ערך שאינו D/C                : %d" % len(junk))
    if junk_values:
        print("  הערכים שנמצאו:")
        for val, n in junk_values.most_common(15):
            print("    %-24s %d" % (repr(val), n))
    if req_missing:
        print("שדות חובה שלא מופו           : %s" % ", ".join(req_missing))
    print("-" * 52)

    if new_rejects == 0 and not junk:
        print("תקין — האכיפה לא תפסול אף שורה שנטענת היום.")
    else:
        print("לתשומת לב: %d שורות שנטענות היום ייפסלו אחרי האכיפה." % new_rejects)
        if junk:
            print("           ועוד %d שורות עם ערך שאינו D/C (ראה רשימה למעלה)." % len(junk))
        print("           שורות שנפסלות יוצאות ל-%s_rejected.xlsx ולא לקובץ הטעינה." % SCREEN)

    # פירוט לפי תנועה — תנועה שמאבדת חלק משורותיה תצא לא מאוזנת
    txn = jc.get("txn")
    if txn and new_rejects:
        bad_txn = {}
        for r in blank:
            if r in allzero_blank:
                continue
            bad_txn.setdefault(str(cell(r, txn) or "").strip(), 0)
            bad_txn[str(cell(r, txn) or "").strip()] += 1
        print()
        print("תנועות שיאבדו שורות: %d (מתוך %d)"
              % (len(bad_txn), len({str(cell(r, txn) or "").strip() for r in rows})))
        for k, n in list(sorted(bad_txn.items(), key=lambda kv: -kv[1]))[:10]:
            print("    תנועה %-14s — %d שורות" % (k or "(ללא מספר)", n))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
