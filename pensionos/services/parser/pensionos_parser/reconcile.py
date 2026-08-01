"""שלב 6 — Reconcile.

איחוד, דדופליקציה ואימות זהות. הבדיקה הקריטית כאן היא אימות שיוך נושא
המידע: קובץ שמכיל ת"ז שאינה של הלקוח שביקשנו עבורו הוא אירוע אבטחה, לא
תקלת נתונים.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import date

from .issues import Code, IssueCollector
from .models import Product, ProductStatus, ProductType, Subject
from .transforms import is_valid_national_id, normalize_national_id

# חשבון ללא הפקדות וללא יתרה משמעותית — מקופל ב-UI תחת "לא פעילים",
# אך לעולם לא נמחק: הוא עדיין חלק מהתמונה המלאה של הלקוח.
DORMANT_BALANCE_THRESHOLD = 1.0


def national_id_hmac(national_id: str, key: bytes) -> str:
    """HMAC דטרמיניסטי לחיפוש ולהשוואה — לעולם לא שומרים ת"ז גלויה.

    המפתח הוא per-tenant, כך שאותה ת"ז אצל שתי סוכנויות מניבה hash שונה
    ולא ניתן להצליב לקוחות בין סוכנויות.
    """
    normalized = normalize_national_id(national_id) or ""
    return hmac.new(key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_subject(
    subject: Subject | None,
    issues: IssueCollector,
    *,
    expected_national_id_hash: str | None = None,
    hmac_key: bytes | None = None,
) -> bool:
    """אימות שהקובץ אכן שייך ללקוח שביקשנו עבורו.

    מחזיר False אם יש להעביר את הקובץ להסגר (Quarantine).
    """
    if subject is None or not subject.national_id:
        issues.error(
            Code.MISSING_SUBJECT,
            "הקובץ אינו כולל את פרטי נושא המידע ולכן לא ניתן לשייכו ללקוח",
        )
        return False

    if not is_valid_national_id(subject.national_id):
        issues.warning(
            Code.INVALID_NATIONAL_ID,
            "תעודת הזהות בקובץ אינה עוברת ולידציית ספרת ביקורת",
            canonical_field="national_id",
        )

    if expected_national_id_hash and hmac_key:
        actual = national_id_hmac(subject.national_id, hmac_key)
        if not hmac.compare_digest(actual, expected_national_id_hash):
            # אירוע אבטחה P1: חשד לדליפת מידע בין לקוחות
            issues.blocker(
                Code.SUBJECT_MISMATCH,
                "אי-התאמה בזיהוי נושא המידע — הקובץ נחסם והועבר לבדיקה",
                canonical_field="national_id",
                context={"security_alert": True},
            )
            return False
    return True


def _prefer(existing: Product, candidate: Product) -> Product:
    """בדיווח כפול — הרשומה העדכנית מנצחת; בתיקו, השלמה יותר."""
    e_date = existing.report_date or date.min
    c_date = candidate.report_date or date.min
    if c_date > e_date:
        return candidate
    if c_date < e_date:
        return existing
    return candidate if candidate.data_completeness > existing.data_completeness else existing


def deduplicate(products: list[Product], issues: IssueCollector) -> tuple[list[Product], int]:
    """אותו חשבון מדווח לעיתים פעמיים — בשני קבצים או פעמיים באותו קובץ."""
    merged: dict[tuple[str, str, str], Product] = {}
    duplicates = 0
    for product in products:
        key = product.dedup_key
        if key in merged:
            duplicates += 1
            issues.info(
                Code.DUPLICATE_ACCOUNT,
                f"חשבון {product.policy_number} דווח יותר מפעם אחת — נשמר הדיווח העדכני",
                entity_ref=f"policy:{product.policy_number}",
            )
            merged[key] = _prefer(merged[key], product)
        else:
            merged[key] = product
    return list(merged.values()), duplicates


def enrich(products: list[Product], issues: IssueCollector) -> list[Product]:
    """השלמות נגזרות שאינן מגיעות מהקובץ אך נדרשות לחוקי הסיכון."""
    for product in products:
        # is_pre_2013 — מזין את R-PEN-001 (מקדם קצבה מובטח)
        if product.join_date is not None:
            product.is_pre_2013 = product.join_date < date(2013, 1, 1)

        # אם דווח ערך מקדם אך לא דווח הדגל — הקיום נגזר מהערך
        if product.has_guaranteed_annuity_factor is None and product.guaranteed_factor_value:
            product.has_guaranteed_annuity_factor = product.guaranteed_factor_value > 0

        # חשבון רדום
        balance = product.total_balance or 0.0
        product.is_dormant = (
            product.status in (ProductStatus.PAID_UP, ProductStatus.FROZEN)
            and balance < DORMANT_BALANCE_THRESHOLD
        )

        # מוצר שאיננו מזהים מוצג ללקוח, אך חסום לשימוש בהמלצה
        if product.product_type == ProductType.UNKNOWN:
            issues.warning(
                Code.UNKNOWN_PRODUCT_TYPE,
                f"סוג המוצר של חשבון {product.policy_number} לא זוהה — "
                "המוצר יוצג בתיק אך לא ניתן לכלול אותו בהמלצה",
                entity_ref=f"policy:{product.policy_number}",
                context={"blocks_recommendation": True},
            )
    return products
