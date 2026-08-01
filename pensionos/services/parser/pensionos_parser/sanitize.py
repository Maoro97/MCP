"""שלב 3 בצנרת — Sanitize.

התקלה מס' 1 בקבצי המסלקה בשטח: קובץ שמצהיר `encoding="UTF-8"` אבל הבייטים
בפועל הם windows-1255. הצהרה שקרית לא מייצרת שגיאה — היא מייצרת ג'יבריש
שנשמר בשקט למסד הנתונים. לכן אנחנו לא סומכים על ההצהרה, אלא מאמתים אותה.
"""

from __future__ import annotations

import re
import unicodedata

from charset_normalizer import from_bytes

from .models import SanitizeReport

# תווי בקרה שאינם חוקיים ב-XML 1.0 (למעט TAB/LF/CR)
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")

# סימני כיווניות: בלתי-נראים, שוברים השוואת מחרוזות, חיפוש ומיון בעברית
_BIDI_MARKS = re.compile("[‎‏‪-‮⁦-⁩]")

_DECLARED_ENC = re.compile(rb"""encoding\s*=\s*["']([\w\-]+)["']""", re.IGNORECASE)
_XML_DECL = re.compile(r"^\s*<\?xml[^>]*\?>")

# קידודים נפוצים בקבצי המסלקה, לפי סדר סבירות.
# utf-8 ראשון בכוונה: פענוח utf-8 הוא strict ונכשל כמעט תמיד על בייטים
# של cp1255, ולכן הוא מסנן בעצמו. הכיוון ההפוך לא נכון — cp1255 "מצליח"
# על כל רצף בייטים ויוצר עברית מזויפת מקובץ utf-8 תקין.
_HEBREW_FALLBACKS = ("utf-8", "cp1255", "iso-8859-8")

# טווח העברית ב-Unicode
_HEBREW = re.compile("[֐-׿]")

# חתימת mojibake אופיינית: עברית ב-cp1255 שפוענחה כ-latin-1/utf-8 יוצרת
# רצפים של תווים לטיניים מוטעמים ותווי בקרה גבוהים.
_MOJIBAKE_HINT = re.compile("[À-ÿ]{2,}|[-]")


def _looks_like_mojibake(text: str, sample: int = 20000) -> bool:
    """היוריסטיקה: האם הטקסט 'התפרק' בפענוח?

    שני סימנים: (א) רצפים לטיניים מוטעמים שאין להם מה לחפש בקובץ עברי,
    (ב) קובץ שאמור להיות עברי ואין בו ולו תו עברי אחד.
    """
    head = text[:sample]
    hits = len(_MOJIBAKE_HINT.findall(head))
    if hits >= 3:
        return True
    # החתימה הקלאסית של UTF-8 שנקרא כ-cp1255: כל אות עברית מקבלת קידומת '×'
    # (וב-latin-1 הקידומת היא 'Ã'). זו ראיה חזקה יותר מכל היוריסטיקה אחרת.
    if head.count("×") + head.count("Ã") >= 3:
        return True
    # קובץ מסלקה תמיד מכיל שמות בעברית. אם אין עברית בכלל אבל יש תווים
    # לא-ASCII — הפענוח ייצר אלפבית זר (קירילי/יווני) מבייטים עבריים.
    # הסף נמוך בכוונה: קובץ אמיתי ללא עברית כלל הוא ממילא חשוד.
    non_ascii = sum(1 for c in head if ord(c) > 127)
    if non_ascii >= 8 and not _HEBREW.search(head):
        return True
    return False


def _decode(raw: bytes, report: SanitizeReport) -> str:
    declared = None
    if m := _DECLARED_ENC.search(raw[:400]):
        declared = m.group(1).decode("ascii", errors="replace").lower()
    report.declared_encoding = declared

    # ניסיון 1 — לפי ההצהרה
    if declared:
        try:
            text = raw.decode(declared)
            if "�" not in text and not _looks_like_mojibake(text):
                report.detected_encoding = declared
                return text
            report.fixes.append(f"declared_encoding_rejected:{declared}")
        except (UnicodeDecodeError, LookupError):
            report.fixes.append(f"declared_encoding_invalid:{declared}")

    # ניסיון 2 — קידודים עבריים מוכרים, לפני הזיהוי הסטטיסטי.
    # הסדר הזה מכוון: charset-normalizer מזהה בייטים של cp1255 כקירילית
    # באותה רמת ביטחון, כי סטטיסטית שתי השפות דומות בטווח הזה. אנחנו
    # יודעים משהו שהוא לא יודע — הקובץ הזה בא מהמסלקה הפנסיונית בישראל.
    for enc in _HEBREW_FALLBACKS:
        if enc == declared:
            continue  # כבר נדחה למעלה
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        if "�" not in text and not _looks_like_mojibake(text):
            report.detected_encoding = enc
            report.fixes.append(f"reencoded_from_{enc}")
            return text

    # ניסיון 3 — זיהוי סטטיסטי, כמוצא אחרון לפני פענוח מאבד
    best = from_bytes(raw).best()
    if best is not None and best.encoding:
        try:
            text = str(best)
            if "�" not in text and not _looks_like_mojibake(text):
                report.detected_encoding = best.encoding
                report.fixes.append(f"reencoded_from_{best.encoding}")
                return text
        except (UnicodeDecodeError, LookupError):  # pragma: no cover
            pass

    # מוצא אחרון: לא מאבדים את הקובץ, מסמנים את הפגיעה
    enc = declared or "cp1255"
    report.detected_encoding = enc
    report.fixes.append(f"lossy_decode:{enc}")
    return raw.decode(enc, errors="replace")


def sanitize(raw: bytes) -> tuple[str, SanitizeReport]:
    """מחזיר XML נקי כמחרוזת + דוח תיקונים לאודיט.

    הדוח נשמר ב-`clearing.parse_jobs.sanitize_report` — כל תיקון שביצענו
    על קובץ של צד שלישי חייב להיות מתועד.
    """
    report = SanitizeReport(bytes_in=len(raw))

    # 1. BOM — כולל BOM כפול, שנפוץ בקבצים שעברו כמה מערכות
    while raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
        report.fixes.append("utf8_bom_stripped")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        report.fixes.append("utf16_bom_detected")

    # 2. פענוח אמין
    text = _decode(raw, report)

    # 3. BOM שנותר באמצע הקובץ (איחוד קבצים גרוע)
    if "﻿" in text:
        text = text.replace("﻿", "")
        report.fixes.append("inline_bom_stripped")

    # 4. תווי בקרה בלתי-חוקיים — הגורם השכיח לקריסת parser
    text, n = _ILLEGAL_XML.subn("", text)
    if n:
        report.fixes.append(f"illegal_control_chars:{n}")

    # 5. סימני כיווניות
    text, n = _BIDI_MARKS.subn("", text)
    if n:
        report.fixes.append(f"bidi_marks:{n}")

    # 6. נרמול Unicode — קריטי להשוואת שמות ולחיפוש בעברית
    normalized = unicodedata.normalize("NFC", text)
    if normalized != text:
        report.fixes.append("unicode_nfc_normalized")
    text = normalized

    # 7. הצהרת הקידוד המקורית כבר לא נכונה (הטקסט בזיכרון הוא Unicode).
    #    השארתה תגרום ל-lxml לנסות לפענח מחדש ולשבור את מה שתיקנו.
    if _XML_DECL.match(text):
        text = _XML_DECL.sub('<?xml version="1.0"?>', text, count=1)
        report.fixes.append("xml_declaration_rewritten")

    report.chars_out = len(text)
    return text, report
