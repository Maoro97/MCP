"""מודל הנתונים הקנוני של מנוע הפענוח.

זהו ה-Anti-Corruption Layer: מכאן והלאה שום רכיב במערכת לא רואה שמות תגים
של המסלקה. הפלט תואם לחוזה שב-`04-tech-stack.md §4`.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .issues import Issue

PARSER_VERSION = "1.0.0"


class ProductType(StrEnum):
    PENSION_COMPREHENSIVE = "pension_comprehensive"
    PENSION_GENERAL = "pension_general"
    PENSION_OLD = "pension_old"
    PROVIDENT_FUND = "provident_fund"
    STUDY_FUND = "study_fund"
    MANAGERS_INSURANCE = "managers_insurance"
    PROVIDENT_INVESTMENT = "provident_investment"
    OTHER = "other"
    UNKNOWN = "unknown"


class ProductStatus(StrEnum):
    ACTIVE = "active"
    PAID_UP = "paid_up"  # מסולק
    FROZEN = "frozen"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class ParseStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    NO_DATA = "no_data"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class Provenance(BaseModel):
    """מאיפה בדיוק הגיע כל ערך — דרישת ציות, לא נוחות דיבוג.

    בביקורת חייבים להראות מאיזה תג ב-XML הגיע כל מספר בטבלת ההשוואה.
    """

    xpath: str
    raw: str | None = None
    confidence: float = 1.0
    fixes: list[str] = Field(default_factory=list)


class Coverage(BaseModel):
    coverage_type: str | None = None
    coverage_name: str | None = None
    sum_insured: float | None = None
    monthly_benefit: float | None = None
    cost_monthly: float | None = None
    waiting_period_m: int | None = None
    is_active: bool = True


class Beneficiary(BaseModel):
    full_name: str | None = None
    relation: str | None = None
    share_pct: float | None = None
    updated_on: date | None = None


class Subject(BaseModel):
    """נושא המידע — הלקוח כפי שהיצרן מדווח עליו."""

    national_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    birth_date: date | None = None


class Product(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    # זיהוי
    provider_code: str | None = None
    provider_name: str | None = None
    policy_number: str | None = None
    product_type: ProductType = ProductType.UNKNOWN
    product_name: str | None = None
    employer_name: str | None = None

    # מחזור חיים
    join_date: date | None = None
    status: ProductStatus = ProductStatus.UNKNOWN
    is_dormant: bool = False
    report_date: date | None = None

    # יתרות
    total_balance: float | None = None
    employee_component: float | None = None
    employer_component: float | None = None
    severance_component: float | None = None
    ytd_yield_pct: float | None = None

    # דמי ניהול
    fee_on_deposit_pct: float | None = None
    fee_on_balance_pct: float | None = None
    fee_agreement_end: date | None = None

    # מסלול
    track_code: str | None = None
    track_name: str | None = None

    # דגלים קריטיים לחוקי הסיכון (R-PEN-001 וכו')
    has_guaranteed_annuity_factor: bool | None = None
    guaranteed_factor_value: float | None = None
    is_pre_2013: bool | None = None

    coverages: list[Coverage] = Field(default_factory=list)
    beneficiaries: list[Beneficiary] = Field(default_factory=list)

    # שקיפות ובקרה
    data_completeness: float = 0.0
    provenance: dict[str, Provenance] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def dedup_key(self) -> tuple[str, str, str]:
        return (
            self.provider_code or "",
            self.policy_number or "",
            str(self.product_type),
        )


class SanitizeReport(BaseModel):
    declared_encoding: str | None = None
    detected_encoding: str | None = None
    fixes: list[str] = Field(default_factory=list)
    bytes_in: int = 0
    chars_out: int = 0


class ParseStats(BaseModel):
    products: int = 0
    coverages: int = 0
    beneficiaries: int = 0
    duplicates_merged: int = 0
    duration_ms: int = 0


class ParseResult(BaseModel):
    """חוזה הפלט של `POST /internal/parse`."""

    status: ParseStatus
    parser_version: str = PARSER_VERSION
    mapping_version: str | None = None
    standard_version: str | None = None
    file_id: str | None = None
    sanitize_report: SanitizeReport = Field(default_factory=SanitizeReport)
    subject: Subject | None = None
    provider_code: str | None = None
    products: list[Product] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    stats: ParseStats = Field(default_factory=ParseStats)

    @property
    def is_usable(self) -> bool:
        """האם הפלט ראוי לכניסה לשכבה הקנונית."""
        return self.status in (ParseStatus.SUCCEEDED, ParseStatus.PARTIAL)
