"""תזמור הצנרת: Land → Sanitize → Extract → Normalize → Reconcile.

זהו ה-entry point היחיד של המנוע. השירות (`POST /internal/parse`) וה-CLI
שניהם קוראים ל-`parse_bytes`.
"""

from __future__ import annotations

import time
from typing import Any

from lxml import etree

from .extract import ExtractedRecord, extract_children, extract_record
from .issues import Code, IssueCollector, Severity
from .mappings import (
    MappingRegistry,
    UnknownStandardVersionError,
    detect_standard_version,
)
from .models import (
    PARSER_VERSION,
    Beneficiary,
    Coverage,
    ParseResult,
    ParseStats,
    ParseStatus,
    Product,
    ProductStatus,
    ProductType,
    SanitizeReport,
    Subject,
)
from .reconcile import deduplicate, enrich, verify_subject
from .sanitize import sanitize
from .xmlsafe import XmlTooLargeError, iter_elements

# סמנים לתשובת "אין מידע" מיצרן — לא כשל, אלא מידע לגיטימי שיש להציג לסוכן
_NO_DATA_MARKERS = ("<EIN-MEIDA>1<", "<KOD-SIBAT-DCHIYA>", "<AIN-NETUNIM>")


def _to_product(
    record: ExtractedRecord,
    children: dict[str, list[ExtractedRecord]],
    provider_code: str | None,
    provider_name: str | None,
    field_count: int,
) -> Product:
    v = record.values
    product = Product(
        provider_code=provider_code,
        provider_name=provider_name,
        policy_number=v.get("policy_number"),
        product_type=ProductType(v.get("product_type") or "unknown"),
        product_name=v.get("product_name"),
        employer_name=v.get("employer_name"),
        join_date=v.get("join_date"),
        status=ProductStatus(v.get("status") or "unknown"),
        report_date=v.get("report_date"),
        total_balance=v.get("total_balance"),
        employee_component=v.get("employee_component"),
        employer_component=v.get("employer_component"),
        severance_component=v.get("severance_component"),
        ytd_yield_pct=v.get("ytd_yield_pct"),
        fee_on_deposit_pct=v.get("fee_on_deposit_pct"),
        fee_on_balance_pct=v.get("fee_on_balance_pct"),
        fee_agreement_end=v.get("fee_agreement_end"),
        track_code=v.get("track_code"),
        track_name=v.get("track_name"),
        has_guaranteed_annuity_factor=v.get("has_guaranteed_annuity_factor"),
        guaranteed_factor_value=v.get("guaranteed_factor_value"),
        data_completeness=record.completeness(field_count),
        provenance=record.provenance,
        raw=dict(record.raw),
    )
    for cov in children.get("coverages", []):
        c = cov.values
        product.coverages.append(
            Coverage(
                coverage_type=c.get("coverage_type"),
                coverage_name=c.get("coverage_name"),
                sum_insured=c.get("sum_insured"),
                monthly_benefit=c.get("monthly_benefit"),
                cost_monthly=c.get("cost_monthly"),
                waiting_period_m=c.get("waiting_period_m"),
            )
        )
    for ben in children.get("beneficiaries", []):
        b = ben.values
        product.beneficiaries.append(
            Beneficiary(
                full_name=b.get("full_name"),
                relation=b.get("relation"),
                share_pct=b.get("share_pct"),
                updated_on=b.get("updated_on"),
            )
        )
    return product


def _decide_status(
    issues: IssueCollector, products: list[Product], no_data: bool
) -> ParseStatus:
    if issues.count(Severity.BLOCKER):
        return ParseStatus.QUARANTINED
    if no_data and not products:
        return ParseStatus.NO_DATA
    if not products:
        return ParseStatus.FAILED
    if issues.count(Severity.ERROR):
        return ParseStatus.PARTIAL
    return ParseStatus.SUCCEEDED


def parse_bytes(
    raw: bytes,
    *,
    file_id: str | None = None,
    expected_national_id_hash: str | None = None,
    hmac_key: bytes | None = None,
    registry: MappingRegistry | None = None,
    max_bytes: int | None = None,
) -> ParseResult:
    """מפענח קובץ מסלקה בודד ומחזיר את התוצאה הקנונית.

    הפונקציה לעולם לא זורקת חריגה על קלט פגום: כל כשל מתורגם לסטטוס
    ולרשימת חריגים, כדי שהקובץ הגולמי לא ילך לאיבוד ולא תידרש פנייה
    חוזרת (בתשלום) למסלקה.
    """
    started = time.perf_counter()
    issues = IssueCollector()

    # --- Sanitize -------------------------------------------------
    try:
        text, sreport = sanitize(raw)
    except Exception as exc:  # pragma: no cover - הגנה אחרונה
        return ParseResult(
            status=ParseStatus.FAILED,
            file_id=file_id,
            issues=[
                IssueCollector()
                .error(Code.MALFORMED_XML, f"לא ניתן לקרוא את הקובץ: {exc}")
                .model_copy()
            ],
        )

    if any(f.startswith(("declared_encoding_", "reencoded_from_")) for f in sreport.fixes):
        issues.info(
            Code.ENCODING_MISMATCH,
            f"קידוד הקובץ תוקן אוטומטית "
            f"(הוצהר: {sreport.declared_encoding or 'לא הוצהר'}, "
            f"בפועל: {sreport.detected_encoding})",
        )
    if any(f.startswith("illegal_control_chars") for f in sreport.fixes):
        issues.info(Code.ILLEGAL_CHARS, "הוסרו תווי בקרה לא חוקיים מהקובץ")

    # --- Registry -------------------------------------------------
    standard_version = detect_standard_version(text)
    try:
        registry = registry or MappingRegistry.load(standard_version or "2.9")
    except UnknownStandardVersionError:
        issues.blocker(
            Code.UNKNOWN_STANDARD_VERSION,
            f"גרסת מבנה אחיד שאינה נתמכת ({standard_version}) — "
            "הקובץ הועבר לבדיקת צוות ולא פוענח",
        )
        return ParseResult(
            status=ParseStatus.QUARANTINED,
            file_id=file_id,
            standard_version=standard_version,
            sanitize_report=sreport,
            issues=issues.issues,
        )

    # --- Extract --------------------------------------------------
    subject: Subject | None = None
    provider_code: str | None = None
    provider_name: str | None = None
    products: list[Product] = []
    coverages = beneficiaries = 0

    product_section = registry.section("product")
    field_count = len(product_section.fields)

    try:
        for elem in iter_elements(
            text,
            registry.stream_tags,
            max_bytes=max_bytes or 200 * 1024 * 1024,
        ):
            tag = etree.QName(elem).localname if elem.tag is not etree.Comment else ""

            if tag == registry.section("provider").tag:
                rec = extract_record(elem, registry.section("provider"), registry, issues)
                provider_code = rec.values.get("provider_code")
                provider_name = rec.values.get("provider_name")
                # מרגע שידוע היצרן — עוברים למיפוי שכולל את הדריסות שלו
                product_section = registry.section("product", provider_code)
                field_count = len(product_section.fields)

            elif tag == registry.section("subject").tag:
                rec = extract_record(elem, registry.section("subject"), registry, issues)
                subject = Subject(
                    national_id=rec.values.get("national_id"),
                    first_name=rec.values.get("first_name"),
                    last_name=rec.values.get("last_name"),
                    birth_date=rec.values.get("birth_date"),
                )

            elif tag == product_section.tag:
                ref = None
                record = extract_record(elem, product_section, registry, issues, ref)
                ref = f"policy:{record.values.get('policy_number')}"
                if "policy_number" in record.missing_required:
                    continue  # רשומה ללא מזהה אינה ניתנת לשיוך
                kids = extract_children(elem, product_section, registry, issues, ref)
                coverages += len(kids.get("coverages", []))
                beneficiaries += len(kids.get("beneficiaries", []))
                products.append(
                    _to_product(record, kids, provider_code, provider_name, field_count)
                )

    except XmlTooLargeError as exc:
        issues.blocker(
            Code.ARCHIVE_LIMIT_EXCEEDED,
            f"הקובץ חורג מהמגבלות המותרות ולא פוענח ({exc})",
        )
        return ParseResult(
            status=ParseStatus.QUARANTINED,
            file_id=file_id,
            standard_version=standard_version,
            mapping_version=registry.version,
            sanitize_report=sreport,
            issues=issues.issues,
        )
    except etree.XMLSyntaxError as exc:
        # recover=True אמור למנוע את זה; אם הגענו לכאן הקובץ בלתי-קריא
        issues.error(Code.MALFORMED_XML, f"מבנה ה-XML פגום ולא ניתן לפענוח ({exc.msg})")

    # --- Reconcile ------------------------------------------------
    no_data = any(marker in text for marker in _NO_DATA_MARKERS)
    if no_data and not products:
        who = provider_name or provider_code or ""
        issues.info(
            Code.NO_DATA_RESPONSE,
            f"היצרן {who} דיווח כי אין מידע עבור הלקוח".replace("  ", " ").strip(),
        )
    elif not products:
        issues.error(Code.NO_ACCOUNTS, "לא נמצאו חשבונות או פוליסות בקובץ")

    subject_ok = verify_subject(
        subject,
        issues,
        expected_national_id_hash=expected_national_id_hash,
        hmac_key=hmac_key,
    )
    if not subject_ok and issues.has(Code.SUBJECT_MISMATCH):
        products = []  # לא מכניסים לשכבה הקנונית נתונים שאינם של הלקוח

    products, duplicates = deduplicate(products, issues)
    products = enrich(products, issues)

    duration_ms = int((time.perf_counter() - started) * 1000)
    return ParseResult(
        status=_decide_status(issues, products, no_data),
        parser_version=PARSER_VERSION,
        mapping_version=registry.version,
        standard_version=standard_version,
        file_id=file_id,
        sanitize_report=sreport,
        subject=subject,
        provider_code=provider_code,
        products=products,
        issues=issues.issues,
        stats=ParseStats(
            products=len(products),
            coverages=coverages,
            beneficiaries=beneficiaries,
            duplicates_merged=duplicates,
            duration_ms=duration_ms,
        ),
    )


def parse_file(path: str, **kwargs: Any) -> ParseResult:
    with open(path, "rb") as fh:
        return parse_bytes(fh.read(), file_id=kwargs.pop("file_id", path), **kwargs)


__all__ = ["parse_bytes", "parse_file", "ParseResult", "SanitizeReport"]
