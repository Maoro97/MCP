"""בדיקות נרמול ערכים — הסטיות שראינו בדיווחי היצרנים."""

from __future__ import annotations

from datetime import date

import pytest

from pensionos_parser.issues import Code
from pensionos_parser.transforms import (
    as_bool,
    as_code,
    as_date,
    as_decimal,
    as_percent,
    is_valid_national_id,
    normalize_national_id,
)


class TestDecimal:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("842100.55", 842100.55),
            ("1,284,300.75", 1284300.75),  # מפריד אלפים
            ("0,22", 0.22),  # פסיק כנקודה עשרונית
            ("1,234.50-", -1234.50),  # מינוס עוקב (מורשת mainframe)
            ("  310500  ", 310500.0),
            ("₪ 5,000", 5000.0),
            ("-42", -42.0),
        ],
    )
    def test_variants(self, raw, expected):
        assert as_decimal(raw).value == pytest.approx(expected)

    def test_thousands_separator_not_confused_with_decimal_comma(self):
        assert as_decimal("1,234").value == 1234.0
        assert as_decimal("0,5").value == 0.5

    @pytest.mark.parametrize("raw", ["", "   ", "N/A", "לא ידוע", "abc"])
    def test_non_numeric_becomes_none(self, raw):
        assert as_decimal(raw).value is None

    def test_bad_format_is_flagged(self):
        assert as_decimal("12..34").hint == Code.BAD_FORMAT

    def test_zero_can_mean_unknown(self):
        """'0' בדמי ניהול הוא כמעט תמיד 'לא דווח' ולא 'אפס'."""
        v = as_decimal("0", allow_zero=False)
        assert v.value is None
        assert v.hint == Code.MISSING_FIELD
        assert "zero_as_null" in v.fixes

    def test_zero_allowed_by_default(self):
        assert as_decimal("0").value == 0.0


class TestPercent:
    def test_percent_sign_stripped(self):
        assert as_percent("0.50%").value == 0.5

    def test_fraction_converted_and_flagged(self):
        """יצרן שמדווח 0.0035 מתכוון ל-0.35% — אבל זו היוריסטיקה, לא ודאות."""
        v = as_percent("0.0035", fraction_threshold=0.06)
        assert v.value == pytest.approx(0.35)
        assert v.hint == Code.AMBIGUOUS_PERCENT
        assert v.confidence < 1.0
        assert "fraction_to_percent" in v.fixes

    def test_ordinary_percent_untouched(self):
        v = as_percent("1.05", fraction_threshold=0.06)
        assert v.value == 1.05
        assert v.hint is None

    def test_explicit_sign_beats_heuristic(self):
        """'0.005%' זה באמת 0.005% — סימן ה-% גובר על ההיוריסטיקה."""
        v = as_percent("0.005%", fraction_threshold=0.06)
        assert v.value == 0.005


class TestDate:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("20260312", date(2026, 3, 12)),
            ("2026-03-12", date(2026, 3, 12)),
            ("12/03/2026", date(2026, 3, 12)),
            ("01.06.2009", date(2009, 6, 1)),
            ("202603", date(2026, 3, 1)),
        ],
    )
    def test_formats(self, raw, expected):
        assert as_date(raw).value == expected

    @pytest.mark.parametrize("raw", ["00000000", "0", "99999999", "", "19000101"])
    def test_null_sentinels(self, raw):
        assert as_date(raw).value is None

    def test_out_of_range_rejected(self):
        assert as_date("31/12/2999").hint is not None

    def test_unparseable_flagged(self):
        assert as_date("March 2026").hint == Code.BAD_FORMAT


class TestCodes:
    TABLE = {"1": "pension_comprehensive", "6": "managers_insurance"}

    def test_known_code(self):
        assert as_code("1", self.TABLE).value == "pension_comprehensive"

    def test_unknown_code_never_guessed(self):
        """ניחוש סוג מוצר עלול לגרור המלצה שגויה — לכן default + חריג."""
        v = as_code("99", self.TABLE, default="unknown")
        assert v.value == "unknown"
        assert v.hint == Code.UNKNOWN_CODE_VALUE
        assert v.confidence == 0.0


class TestBool:
    @pytest.mark.parametrize("raw", ["1", "true", "Y", "כן"])
    def test_truthy(self, raw):
        assert as_bool(raw).value is True

    @pytest.mark.parametrize("raw", ["0", "false", "N", "לא"])
    def test_falsy(self, raw):
        assert as_bool(raw).value is False

    def test_unknown(self):
        assert as_bool("maybe").hint == Code.BAD_FORMAT


class TestNationalId:
    def test_zero_padded(self):
        assert normalize_national_id("39472519") == "039472519"

    def test_strips_separators(self):
        assert normalize_national_id("039-472-519") == "039472519"

    @pytest.mark.parametrize("value", ["039472519", "021234562", "044556678"])
    def test_valid_checksum(self, value):
        assert is_valid_national_id(value)

    @pytest.mark.parametrize("value", ["039472518", "123456789", "", None, "1234567890"])
    def test_invalid_checksum(self, value):
        assert not is_valid_national_id(value)
