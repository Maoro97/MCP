"""שלב 4+5 — Extract & Normalize.

מנוע גנרי שמונע ממפרט המיפוי. אין כאן שום ידע על שדה ספציפי: הוספת שדה
או תמיכה ביצרן חדש היא שינוי ב-YAML/DB בלבד.

עיקרון: ה-Extractor לעולם לא נכשל על שדה חסר. הוא מייצר ערך + provenance +
חריג, ומדיניות `on_missing` היא שמחליטה מה המשמעות.
"""

from __future__ import annotations

from typing import Any

from lxml import etree

from .issues import Code, IssueCollector, Severity
from .mappings import FieldSpec, MappingRegistry, SectionSpec
from .models import Provenance
from .transforms import TRANSFORMS, Value, as_code
from .xmlsafe import element_exists, first_text


class ExtractedRecord:
    """רשומה שחולצה: ערכים קנוניים + מאיפה הגיע כל אחד."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.provenance: dict[str, Provenance] = {}
        self.raw: dict[str, str] = {}
        self.missing_required: list[str] = []

    def completeness(self, total_fields: int) -> float:
        if not total_fields:
            return 0.0
        filled = sum(1 for v in self.values.values() if v is not None)
        return round(filled / total_fields, 3)


def _apply_transform(spec: FieldSpec, raw: str | None, registry: MappingRegistry) -> Value:
    if spec.code_table:
        return as_code(raw, registry.code_table(spec.code_table), spec.default)
    fn = TRANSFORMS.get(spec.type, TRANSFORMS["string"])
    return fn(raw, **spec.args)


def _resolve_xpath(elem: etree._Element, spec: FieldSpec) -> tuple[str | None, str, bool]:
    """מחזיר (טקסט, ה-xpath ששימש, האם התג קיים בכלל).

    ההבחנה בין "תג חסר" ל"תג ריק" נשמרת: שניהם מניבים None, אבל רק במקרה
    השני אנחנו יודעים שהיצרן דיווח על השדה במפורש כריק.
    """
    exists = False
    for xpath in spec.all_xpaths:
        if element_exists(elem, xpath):
            exists = True
            text = first_text(elem, xpath)
            if text is not None:
                return text, xpath, True
    return None, spec.xpath, exists


def extract_record(
    elem: etree._Element,
    section: SectionSpec,
    registry: MappingRegistry,
    issues: IssueCollector,
    entity_ref: str | None = None,
) -> ExtractedRecord:
    record = ExtractedRecord()

    for spec in section.fields:
        raw, used_xpath, tag_exists = _resolve_xpath(elem, spec)
        result = _apply_transform(spec, raw, registry)

        # ולידציית טווח — ערך מחוץ לטווח סביר מעיד על מיפוי או פורמט שגוי
        if result.value is not None and spec.type in ("decimal", "int", "percent"):
            if (spec.minimum is not None and result.value < spec.minimum) or (
                spec.maximum is not None and result.value > spec.maximum
            ):
                issues.warning(
                    Code.OUT_OF_RANGE,
                    f"הערך של '{spec.label_he or spec.canonical}' חורג מהטווח הסביר "
                    f"ולכן לא נקלט (התקבל: {result.raw})",
                    canonical_field=spec.canonical,
                    xpath=used_xpath,
                    raw_value=result.raw,
                    entity_ref=entity_ref,
                )
                result = Value(raw=result.raw, hint=None, confidence=0.0)

        # רמז מהטרנספורם (פורמט לא תקין, אחוז דו-משמעי, קוד לא מוכר)
        if result.hint is not None:
            severity = (
                Severity.INFO if result.hint == Code.AMBIGUOUS_PERCENT else Severity.WARNING
            )
            issues.add(
                severity,
                result.hint,
                _hint_message(result.hint, spec, result),
                canonical_field=spec.canonical,
                xpath=used_xpath,
                raw_value=result.raw,
                entity_ref=entity_ref,
            )

        record.values[spec.canonical] = result.value
        if raw is not None:
            record.raw[spec.canonical] = raw
        record.provenance[spec.canonical] = Provenance(
            xpath=used_xpath,
            raw=result.raw,
            confidence=result.confidence if result.value is not None else 0.0,
            fixes=result.fixes,
        )

        # מדיניות חוסר
        if result.value is None:
            _handle_missing(spec, tag_exists, used_xpath, issues, record, entity_ref)

    return record


def _hint_message(code: Code, spec: FieldSpec, result: Value) -> str:
    label = spec.label_he or spec.canonical
    match code:
        case Code.BAD_FORMAT:
            return f"הערך של '{label}' לא בפורמט צפוי ולכן לא נקלט (התקבל: {result.raw})"
        case Code.AMBIGUOUS_PERCENT:
            return (
                f"'{label}' דווח כשבר עשרוני ({result.raw}) והומר ל-{result.value}% — "
                "מומלץ לאמת מול היצרן"
            )
        case Code.UNKNOWN_CODE_VALUE:
            return f"קוד לא מוכר בשדה '{label}' (התקבל: {result.raw})"
        case Code.MISSING_FIELD:
            return f"'{label}' דווח כאפס — ככל הנראה הנתון לא הועבר בפועל"
        case _:  # pragma: no cover
            return f"בעיה בשדה '{label}' (התקבל: {result.raw})"


def _handle_missing(
    spec: FieldSpec,
    tag_exists: bool,
    xpath: str,
    issues: IssueCollector,
    record: ExtractedRecord,
    entity_ref: str | None,
) -> None:
    label = spec.label_he or spec.canonical
    reason = "התקבל תג ריק" if tag_exists else "השדה לא הועבר כלל"

    if spec.on_missing == "reject":
        record.missing_required.append(spec.canonical)
        issues.error(
            Code.MISSING_FIELD,
            f"חסר נתון חובה '{label}' ({reason}) — הרשומה לא נקלטה",
            canonical_field=spec.canonical,
            xpath=xpath,
            entity_ref=entity_ref,
        )
    elif spec.on_missing == "flag_for_review":
        # שדה שנדרש להנמקה — חוסר בו יחסום את הפקת המסמך בהמשך
        severity = Severity.ERROR if spec.required_for else Severity.WARNING
        issues.add(
            severity,
            Code.MISSING_FIELD,
            f"חסר '{label}' ({reason})"
            + (" — נדרש להשלמה לפני הפקת מסמך הנמקה" if spec.required_for else ""),
            canonical_field=spec.canonical,
            xpath=xpath,
            entity_ref=entity_ref,
            context={"required_for": list(spec.required_for)},
        )
        if spec.required_for:
            record.missing_required.append(spec.canonical)
        if spec.default is not None:
            record.values[spec.canonical] = spec.default


def extract_children(
    elem: etree._Element,
    section: SectionSpec,
    registry: MappingRegistry,
    issues: IssueCollector,
    entity_ref: str | None,
) -> dict[str, list[ExtractedRecord]]:
    out: dict[str, list[ExtractedRecord]] = {}
    for name, child in section.children.items():
        records: list[ExtractedRecord] = []
        if not child.iterate:
            continue
        try:
            nodes = elem.xpath(child.iterate)
        except etree.XPathEvalError:  # pragma: no cover
            nodes = []
        for node in nodes:
            records.append(extract_record(node, child, registry, issues, entity_ref))
        out[name] = records
    return out
