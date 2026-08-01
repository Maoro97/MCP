"""בדיקות מקצה-לקצה מול קורפוס הקבצים.

כל בדיקה כאן מייצגת Edge Case מהקטלוג שב-`01-architecture.md §4`.
"""

from __future__ import annotations

from datetime import date

import pytest

from pensionos_parser.models import ParseStatus, ProductType
from pensionos_parser.pipeline import parse_bytes


class TestHappyPath:
    @pytest.fixture
    def result(self, load):
        return parse_bytes(load("01_clean"), file_id="f-1")

    def test_status_and_metadata(self, result):
        assert result.status == ParseStatus.SUCCEEDED
        assert result.standard_version == "2.9"
        assert result.mapping_version == "2026.03"
        assert result.file_id == "f-1"

    def test_subject(self, result):
        assert result.subject.national_id == "039472519"
        assert result.subject.first_name == "דנה"
        assert result.subject.last_name == "כהן"
        assert result.subject.birth_date == date(1984, 3, 17)

    def test_products(self, result):
        assert result.stats.products == 2
        pension = next(p for p in result.products if p.policy_number == "5512340")
        assert pension.product_type == ProductType.PENSION_COMPREHENSIVE
        assert pension.total_balance == pytest.approx(842100.55)
        assert pension.fee_on_deposit_pct == 1.49
        assert pension.fee_on_balance_pct == 0.22
        assert pension.report_date == date(2026, 3, 12)
        assert pension.track_name == "מסלול תלוי גיל"
        assert pension.provider_name == "מנורה מבטחים"

    def test_children_extracted(self, result):
        pension = next(p for p in result.products if p.policy_number == "5512340")
        assert {c.coverage_type for c in pension.coverages} == {"disability", "survivors"}
        assert pension.coverages[0].monthly_benefit == 9400
        assert pension.coverages[0].waiting_period_m == 3
        assert pension.beneficiaries[0].full_name == "יוסי כהן"
        assert pension.beneficiaries[0].share_pct == 100

    def test_provenance_is_recorded(self, result):
        """דרישת ציות: לכל מספר בטבלת ההשוואה חייב להיות מקור מדויק."""
        pension = next(p for p in result.products if p.policy_number == "5512340")
        prov = pension.provenance["fee_on_balance_pct"]
        assert prov.xpath.endswith("SHEUR-DMEI-NIHUL-ME-HATZVIRA")
        assert prov.raw == "0.22"
        assert prov.confidence == 1.0

    def test_guaranteed_annuity_factor_flag(self, result):
        """הדגל שמזין את חוק R-PEN-001 (חוסם ניוד)."""
        managers = next(p for p in result.products if p.policy_number == "8871200")
        assert managers.product_type == ProductType.MANAGERS_INSURANCE
        assert managers.has_guaranteed_annuity_factor is True
        assert managers.guaranteed_factor_value == 167.4
        assert managers.is_pre_2013 is True
        assert managers.fee_agreement_end == date(2026, 12, 31)


class TestEncodingCorpus:
    def test_cp1255_file_keeps_hebrew(self, load):
        result = parse_bytes(load("02_cp1255"))

        assert result.status == ParseStatus.SUCCEEDED
        assert result.subject.first_name == "דנה"
        assert result.products[0].provider_name == "מנורה מבטחים"
        assert any(i.code == "ENCODING_MISMATCH" for i in result.issues)

    def test_bom_control_and_bidi_file(self, load):
        result = parse_bytes(load("03_bom_control"))

        assert result.status == ParseStatus.SUCCEEDED
        assert result.subject.first_name == "דנה", "סימני BiDi הוסרו מהשם"
        assert "\x00" not in (result.products[0].provider_name or "")


class TestMissingData:
    @pytest.fixture
    def result(self, load):
        return parse_bytes(load("04_empty_tags"))

    def test_partial_status(self, result):
        assert result.status == ParseStatus.PARTIAL

    def test_missing_values_are_none_not_zero(self, result):
        """התקלה שמטעה סוכנים במערכות הקיימות: הצגת חוסר כאפס."""
        p = result.products[0]
        assert p.total_balance is None
        assert p.fee_on_balance_pct is None
        assert p.fee_on_deposit_pct is None, "'0' בדמי ניהול אינו אפס אלא 'לא דווח'"
        assert p.report_date is None

    def test_missing_required_fields_raise_errors(self, result):
        errors = [i for i in result.issues if i.severity == "error"]
        missing = {i.canonical_field for i in errors}
        assert {"total_balance", "fee_on_balance_pct", "report_date"} <= missing

    def test_error_message_names_the_field_in_hebrew(self, result):
        msg = next(i.message_he for i in result.issues if i.canonical_field == "total_balance")
        assert "יתרה צבורה" in msg
        assert "מסמך הנמקה" in msg, "הסוכן צריך לדעת שזה חוסם הפקת מסמך"

    def test_completeness_reflects_gaps(self, result):
        assert result.products[0].data_completeness < 0.7


class TestMessyFormats:
    @pytest.fixture
    def result(self, load):
        return parse_bytes(load("05_messy"))

    def test_thousands_separator_and_decimal_comma(self, result):
        p = result.products[0]
        assert p.total_balance == pytest.approx(1284300.75)
        assert p.fee_on_deposit_pct == pytest.approx(1.49)

    def test_alternate_date_formats(self, result):
        p = result.products[0]
        assert p.report_date == date(2026, 3, 12)
        assert p.join_date == date(2009, 6, 1)

    def test_trailing_minus_yield(self, result):
        assert result.products[0].ytd_yield_pct == pytest.approx(-3.20)

    def test_fraction_percent_flagged_not_silently_fixed(self, result):
        p = result.products[0]
        assert p.fee_on_balance_pct == pytest.approx(0.35)
        assert any(i.code == "AMBIGUOUS_PERCENT" for i in result.issues)
        assert p.provenance["fee_on_balance_pct"].confidence < 1.0


class TestTruncatedFile:
    def test_recovers_what_it_can(self, load):
        """הורדה שנקטעה: לא זורקים את הקובץ, מצילים את מה שיש ומדווחים."""
        result = parse_bytes(load("06_truncated"))

        assert result.status == ParseStatus.PARTIAL
        assert result.subject.national_id == "039472519"
        assert result.stats.products >= 1


class TestProviderBehaviour:
    def test_no_data_response_is_not_a_failure(self, load):
        result = parse_bytes(load("10_no_data"))

        assert result.status == ParseStatus.NO_DATA
        assert result.products == []
        msg = next(i.message_he for i in result.issues if i.code == "NO_DATA_RESPONSE")
        assert "הפניקס" in msg

    def test_duplicate_accounts_keep_latest_report(self, load):
        result = parse_bytes(load("11_duplicate"))

        assert result.stats.products == 1
        assert result.stats.duplicates_merged == 1
        assert result.products[0].report_date == date(2026, 3, 12)
        assert result.products[0].total_balance == pytest.approx(842100.55)

    def test_provider_specific_mapping_override(self, load):
        """יצרן שמדווח תחת נתיב אחר — נפתר בנתונים, לא בקוד."""
        result = parse_bytes(load("12_provider_quirk"))

        assert result.provider_code == "999999999"
        assert result.products[0].fee_on_balance_pct == pytest.approx(0.35)
        assert result.products[0].provenance["fee_on_balance_pct"].xpath.endswith(
            "SHEUR-TZVIRA"
        )

    def test_unknown_product_type_is_shown_but_blocked(self, load):
        result = parse_bytes(load("13_unknown_product"))

        p = result.products[0]
        assert p.product_type == ProductType.UNKNOWN
        blocked = next(i for i in result.issues if i.code == "UNKNOWN_PRODUCT_TYPE")
        assert blocked.context["blocks_recommendation"] is True

    def test_unknown_standard_version_is_quarantined(self, load):
        """אין ניחוש מיפוי על גרסה לא מוכרת."""
        result = parse_bytes(load("14_unknown_standard"))

        assert result.status == ParseStatus.QUARANTINED
        assert result.products == []
        assert any(i.code == "UNKNOWN_STANDARD_VERSION" for i in result.issues)


class TestScale:
    def test_large_file_streams(self, load):
        result = parse_bytes(load("15_large"))

        assert result.status == ParseStatus.SUCCEEDED
        assert result.stats.products == 400
        assert result.stats.coverages == 800

    def test_large_file_is_fast_enough(self, load):
        """יעד NFR: פענוח קובץ ממוצע < 15 שניות."""
        result = parse_bytes(load("15_large"))

        assert result.stats.duration_ms < 15_000


class TestRobustness:
    @pytest.mark.parametrize(
        "payload",
        [b"", b"not xml at all", b"<Mimshak>", b"\x00\x01\x02", b"<?xml?><a/>"],
    )
    def test_never_raises(self, payload):
        """הצנרת לעולם לא זורקת: כל כשל הופך לסטטוס + חריגים."""
        result = parse_bytes(payload)

        assert result.status in tuple(ParseStatus)
        assert not result.is_usable
