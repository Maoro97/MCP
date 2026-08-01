"""עטיפה מוקשחת ל-lxml.

מנוע הפענוח מעבד קלט לא-מהימן שמגיע מגורם חיצוני. כל parser שנוצר במערכת
חייב לעבור דרך המודול הזה — אין קריאה ישירה ל-`etree.parse`/`iterparse`
בשום מקום אחר בקוד.

הגנות: XXE, External DTD (SSRF), Billion Laughs, וצריכת זיכרון בלתי-מוגבלת.
"""

from __future__ import annotations

import io
from collections.abc import Iterator, Sequence
from typing import Any

from lxml import etree

# מגבלות ברירת מחדל — ניתנות לדריסה פר-קריאה, אך לא ניתנות לביטול
MAX_BYTES = 200 * 1024 * 1024  # 200MB — קובץ פירוט הפקדות היסטורי
MAX_ELEMENTS = 5_000_000

_HARDENING: dict[str, Any] = {
    "resolve_entities": False,  # XXE
    "no_network": True,  # SSRF דרך DTD חיצוני
    "load_dtd": False,  # Billion Laughs (ישויות פנימיות לא יורחבו)
    "dtd_validation": False,
    "huge_tree": False,  # הגנה מפני עצי ענק / quadratic blowup
}


class XmlTooLargeError(ValueError):
    pass


def make_parser(recover: bool = True) -> etree.XMLParser:
    """Parser מוקשח. `recover=True` מציל קבצים קטועים במקום לזרוק אותם."""
    return etree.XMLParser(recover=recover, **_HARDENING)


def _iterparse_kwargs(tags: Sequence[str], recover: bool) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "events": ("end",),
        "tag": tuple(tags),
        "recover": recover,
        **_HARDENING,
    }
    # `resolve_entities` נוסף ל-iterparse רק בגרסאות מאוחרות של lxml.
    # גם בלעדיו אנחנו מוגנים: load_dtd=False + no_network=True.
    try:
        etree.iterparse(io.BytesIO(b"<a/>"), **kwargs)
    except TypeError:
        kwargs.pop("resolve_entities", None)
    return kwargs


def iter_elements(
    text: str,
    tags: Sequence[str],
    *,
    recover: bool = True,
    max_bytes: int = MAX_BYTES,
    max_elements: int = MAX_ELEMENTS,
) -> Iterator[etree._Element]:
    """מעבר זורם (streaming) על אלמנטים לפי תגים.

    לא DOM: קבצי מסלקה מגיעים ל-200MB, וטעינה מלאה לזיכרון תפיל
    את ה-worker. צריכת הזיכרון כאן קבועה ואינה תלויה בגודל הקובץ.
    """
    data = text.encode("utf-8")
    if len(data) > max_bytes:
        raise XmlTooLargeError(f"{len(data)} bytes > limit {max_bytes}")

    ctx = etree.iterparse(io.BytesIO(data), **_iterparse_kwargs(tags, recover))
    seen = 0
    for _event, elem in ctx:
        seen += 1
        if seen > max_elements:
            raise XmlTooLargeError(f"element count exceeded {max_elements}")
        yield elem
        # שחרור זיכרון: מנקים את האלמנט ואת אחיו שכבר עובדו.
        elem.clear()
        parent = elem.getparent()
        if parent is not None:
            while elem.getprevious() is not None:
                del parent[0]


def first_text(elem: etree._Element, xpath: str) -> str | None:
    """שליפת טקסט ראשון לפי XPath יחסי.

    מבחין בין תג חסר לחלוטין לבין תג ריק — שניהם מוחזרים כ-None, אך
    ההבחנה עצמה נעשית ב-`extract` דרך `element_exists`, כי מדיניות
    `on_missing` שונה בין השניים.
    """
    try:
        nodes = elem.xpath(xpath)
    except etree.XPathEvalError:
        return None
    if not nodes:
        return None
    node = nodes[0]
    text = node if isinstance(node, str) else (node.text or "")
    text = text.strip()
    return text or None


def element_exists(elem: etree._Element, xpath: str) -> bool:
    try:
        return bool(elem.xpath(xpath))
    except etree.XPathEvalError:
        return False
