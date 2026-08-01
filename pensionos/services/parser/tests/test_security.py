"""בדיקות אבטחה — הקלט מגיע מגורם חיצוני ומטופל כעוין.

הבדיקות האלה חוסמות merge. פגיעה באחת מהן היא רגרסיה באבטחה, לא באג פונקציונלי.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from pensionos_parser.archive import ArchiveLimitError, iter_zip_members
from pensionos_parser.pipeline import parse_bytes
from pensionos_parser.xmlsafe import XmlTooLargeError, iter_elements


class TestXxe:
    def test_local_file_is_not_disclosed(self, load):
        """XXE: ישות חיצונית שמצביעה על /etc/passwd לא נפתרת."""
        result = parse_bytes(load("07_xxe"))

        dumped = result.model_dump_json()
        assert "root:" not in dumped
        assert "/etc/passwd" not in dumped
        assert "bin/bash" not in dumped

    def test_remote_entity_is_not_fetched(self):
        payload = (
            b'<?xml version="1.0"?>\n'
            b"<!DOCTYPE Mimshak [<!ENTITY x SYSTEM "
            b'"http://169.254.169.254/latest/meta-data/">]>\n'
            b"<Mimshak><GIRSAT-MIVNE-ACHID>2.9</GIRSAT-MIVNE-ACHID>"
            b"<YeshutYatzran><KOD-MEZAHE-YATZRAN>&x;</KOD-MEZAHE-YATZRAN>"
            b"</YeshutYatzran></Mimshak>"
        )

        result = parse_bytes(payload)  # no_network=True ⇒ אין ניסיון רשת

        assert "169.254.169.254" not in result.model_dump_json()
        assert "ami-id" not in result.model_dump_json()


class TestEntityExpansion:
    def test_billion_laughs_does_not_explode(self, load):
        """load_dtd=False ⇒ הישויות אינן מוגדרות ואינן מורחבות."""
        result = parse_bytes(load("08_billion"))

        # לא קרסנו, לא צרכנו זיכרון, ולא ייצרנו מחרוזת ענק
        assert len(result.model_dump_json()) < 100_000
        assert "lollollol" not in result.model_dump_json()


class TestSizeLimits:
    def test_oversized_document_is_quarantined(self, load):
        result = parse_bytes(load("15_large"), max_bytes=1024)

        assert result.status == "quarantined"
        assert any(i.code == "ARCHIVE_LIMIT_EXCEEDED" for i in result.issues)

    def test_iter_elements_enforces_byte_limit(self):
        with pytest.raises(XmlTooLargeError):
            list(iter_elements("<a>" + "<b/>" * 100 + "</a>", ["b"], max_bytes=10))

    def test_iter_elements_enforces_element_limit(self):
        with pytest.raises(XmlTooLargeError):
            list(iter_elements("<a>" + "<b/>" * 50 + "</a>", ["b"], max_elements=10))


class TestArchive:
    def _zip(self, members: dict[str, bytes]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in members.items():
                zf.writestr(name, data)
        return buf.getvalue()

    def test_normal_archive_reads(self):
        blob = self._zip({"menora.xml": b"<a/>", "clal.xml": b"<b/>"})

        members = list(iter_zip_members(blob))

        assert {m.name for m in members} == {"menora.xml", "clal.xml"}

    def test_zip_bomb_ratio_rejected(self):
        blob = self._zip({"bomb.xml": b"A" * (20 * 1024 * 1024)})

        with pytest.raises(ArchiveLimitError, match="compression ratio"):
            list(iter_zip_members(blob))

    def test_too_many_files_rejected(self):
        blob = self._zip({f"f{i}.xml": b"<a/>" for i in range(50)})

        with pytest.raises(ArchiveLimitError, match="files"):
            list(iter_zip_members(blob, max_files=10))

    def test_path_traversal_entries_ignored(self):
        blob = self._zip({"../../etc/passwd": b"x", "ok.xml": b"<a/>"})

        names = [m.name for m in iter_zip_members(blob)]

        assert names == ["ok.xml"]


class TestSubjectIsolation:
    def test_wrong_client_file_is_blocked(self, load):
        """קובץ עם ת"ז שאינה של הלקוח = אירוע אבטחה, לא תקלת נתונים."""
        from pensionos_parser.reconcile import national_id_hmac
        from tests.conftest import CLIENT_ID, HMAC_KEY

        result = parse_bytes(
            load("09_subject_mismatch"),
            expected_national_id_hash=national_id_hmac(CLIENT_ID, HMAC_KEY),
            hmac_key=HMAC_KEY,
        )

        assert result.status == "quarantined"
        assert result.products == [], "אסור שנתוני לקוח אחר יגיעו לשכבה הקנונית"
        mismatch = [i for i in result.issues if i.code == "SUBJECT_MISMATCH"]
        assert mismatch and mismatch[0].severity == "blocker"
        assert mismatch[0].context.get("security_alert") is True

    def test_matching_client_passes(self, load):
        from pensionos_parser.reconcile import national_id_hmac
        from tests.conftest import CLIENT_ID, HMAC_KEY

        result = parse_bytes(
            load("01_clean"),
            expected_national_id_hash=national_id_hmac(CLIENT_ID, HMAC_KEY),
            hmac_key=HMAC_KEY,
        )

        assert result.status == "succeeded"
        assert len(result.products) == 2

    def test_hmac_is_tenant_scoped(self):
        """אותה ת"ז אצל שתי סוכנויות חייבת להניב hash שונה."""
        from pensionos_parser.reconcile import national_id_hmac

        a = national_id_hmac("039472519", b"tenant-a-key")
        b = national_id_hmac("039472519", b"tenant-b-key")

        assert a != b
