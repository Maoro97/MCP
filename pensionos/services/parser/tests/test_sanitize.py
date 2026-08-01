"""בדיקות שלב ה-Sanitize — התקלות השכיחות ביותר בקבצי המסלקה."""

from __future__ import annotations

import unicodedata

from pensionos_parser.sanitize import sanitize

HEB = "מנורה מבטחים פנסיה וגמל"


def _wrap(inner: str, declared: str = "utf-8") -> str:
    return f'<?xml version="1.0" encoding="{declared}"?>\n<Mimshak>{inner}</Mimshak>'


def test_cp1255_declared_as_utf8_is_recovered():
    """התקלה מס' 1 בשטח: הצהרת קידוד שקרית."""
    raw = _wrap(f"<SHEM-YATZRAN>{HEB}</SHEM-YATZRAN>").encode("cp1255")

    text, report = sanitize(raw)

    assert HEB in text, "העברית חייבת לשרוד את הפענוח"
    assert report.declared_encoding == "utf-8"
    assert report.detected_encoding in ("cp1255", "windows-1255", "iso-8859-8")
    # התיקון מתועד לאודיט — בין אם ההצהרה נדחתה ובין אם הפענוח לפיה נכשל
    assert any(f.startswith("declared_encoding_") for f in report.fixes)
    assert any(f.startswith("reencoded_from_") for f in report.fixes)


def test_valid_utf8_is_not_touched():
    raw = _wrap(f"<SHEM-YATZRAN>{HEB}</SHEM-YATZRAN>").encode("utf-8")

    text, report = sanitize(raw)

    assert HEB in text
    assert report.detected_encoding == "utf-8"
    assert not any(f.startswith("reencoded") for f in report.fixes)


def test_double_bom_is_stripped():
    raw = b"\xef\xbb\xbf\xef\xbb\xbf" + _wrap("<A>1</A>").encode("utf-8")

    text, report = sanitize(raw)

    assert text.lstrip().startswith("<?xml")
    assert report.fixes.count("utf8_bom_stripped") == 2


def test_illegal_control_characters_removed():
    raw = _wrap("<A>\x00\x01test\x1f</A>").encode("utf-8")

    text, report = sanitize(raw)

    assert "\x00" not in text and "\x1f" not in text
    assert "test" in text
    assert any(f.startswith("illegal_control_chars") for f in report.fixes)


def test_tab_and_newline_are_preserved():
    """TAB/LF/CR חוקיים ב-XML ואסור להסיר אותם."""
    raw = _wrap("<A>a\tb\nc</A>").encode("utf-8")

    text, _ = sanitize(raw)

    assert "\t" in text and "\n" in text


def test_bidi_marks_removed_from_names():
    """סימני כיווניות בלתי-נראים שוברים השוואת מחרוזות ומיון."""
    raw = _wrap("<SHEM-PRATI>‏דנה‎</SHEM-PRATI>").encode("utf-8")

    text, report = sanitize(raw)

    assert "‏" not in text and "‎" not in text
    assert "<SHEM-PRATI>דנה</SHEM-PRATI>" in text
    assert any(f.startswith("bidi_marks") for f in report.fixes)


def test_unicode_normalized_to_nfc():
    """שמות לועזיים בתיק מגיעים לעיתים מפורקים — NFC מונע כפילויות בחיפוש.

    (ניקוד עברי נשאר מפורק גם ב-NFC כי אין לו צורה מורכבת; לכן הבדיקה
    משתמשת בתו לטיני שכן מתאחד.)
    """
    decomposed = unicodedata.normalize("NFD", "José Café")
    raw = _wrap(f"<SHEM-PRATI>{decomposed}</SHEM-PRATI>").encode("utf-8")

    text, report = sanitize(raw)

    assert text == unicodedata.normalize("NFC", text)
    assert "José Café" in text
    assert "unicode_nfc_normalized" in report.fixes


def test_utf8_hebrew_without_declaration_is_not_read_as_cp1255():
    """מלכודת הפוכה: cp1255 'מצליח' על כל בייט ומייצר עברית מזויפת."""
    raw = f"<Mimshak><SHEM-YATZRAN>{HEB}</SHEM-YATZRAN></Mimshak>".encode()

    text, report = sanitize(raw)

    assert HEB in text
    assert report.detected_encoding == "utf-8"


def test_encoding_declaration_is_rewritten():
    """אחרי שתיקנו את הקידוד, ההצהרה המקורית תגרום ל-lxml לשבור אותו שוב."""
    raw = _wrap("<A>1</A>", declared="windows-1255").encode("cp1255")

    text, report = sanitize(raw)

    assert 'encoding="windows-1255"' not in text
    assert "xml_declaration_rewritten" in report.fixes


def test_never_raises_on_garbage():
    """קלט בינארי אקראי לא מפיל את המנוע — מקסימום פענוח מאבד."""
    text, report = sanitize(bytes(range(256)) * 4)

    assert isinstance(text, str)
    assert report.bytes_in == 1024
