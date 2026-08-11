# -*- coding: utf-8 -*-
"""
בדיקות לממשק קליטת הספקים.

הרצה:  python -m unittest discover -s tests -v      (מתוך תיקיית file-loader)

הבדיקות לא נוגעות בפריוריטי אמיתי — הלקוח מוחלף בכפיל שמתעד את מה שנשלח,
כך שאפשר לבדוק את כל המסלול: התחברות → ולידציה → OTP → טעינה → יומן.
"""

import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

# חייב להיקבע לפני ייבוא db/webapp — נתיב המסד נקרא בזמן הייבוא
_TMP = tempfile.mkdtemp(prefix="intake-test-")
os.environ["FILE_LOADER_DB"] = os.path.join(_TMP, "test.db")
os.environ["FILE_LOADER_OUTPUT"] = _TMP
os.environ["INTAKE_SECRET"] = "test-secret-key-for-encryption"
os.environ["SECRET_KEY"] = "test-flask-secret"
os.environ.pop("INTAKE_ADMIN_USER", None)
os.environ.pop("INTAKE_ADMIN_PASSWORD", None)

import webapp                                        # noqa: E402
from intake import auth, otp, priority, schema, security, store, views  # noqa: E402

SCREEN = "SUPPLIERS"

# ספק תקין מינימלי — כל שדות החובה של המסך
VALID = {
    "SUPDES": "א.ב. שיווק והפצה בעמ",
    "SUPNAME": "S1001",
    "STATDES": "פעיל",
    "OWNERLOGIN": "maor",
    "CODE": "ILS",
    "ERPG_SECNAME": "ספקים שוטפים",
    "ERPG_TRIALBALCODE": "300",
}


def tearDownModule():
    shutil.rmtree(_TMP, ignore_errors=True)


# ---------------------------------------------------------------------------
class CatalogTest(unittest.TestCase):
    """הקטלוג שנוצר מהאקסל משקף את הגדרות המסך."""

    def test_mandatory_fields_from_excel(self):
        catalog = schema.load_catalog(SCREEN)
        required = {name for name, f in catalog.items() if f.get("required")}
        self.assertEqual(required, {"SUPDES", "OWNERLOGIN", "STATDES", "CODE",
                                    "ERPG_SECNAME", "ERPG_TRIALBALCODE"})

    def test_widths_and_types(self):
        catalog = schema.load_catalog(SCREEN)
        self.assertEqual(catalog["SUPNAME"]["max_length"], 16)
        self.assertEqual(catalog["SUPDES"]["max_length"], 48)
        self.assertEqual(catalog["CREATEDDATE"]["type"], "date")
        self.assertTrue(catalog["CONFIDENTIAL"]["boolean"])
        self.assertTrue(catalog["PAYDES"]["readonly"])
        self.assertTrue(catalog["SUP"]["system"])

    def test_form_excludes_readonly_and_system(self):
        fields = schema.form_fields(SCREEN, include_advanced=True)
        catalog = schema.load_catalog(SCREEN)
        for name in fields:
            self.assertFalse(catalog[name].get("readonly"), name)
            self.assertFalse(catalog[name].get("system"), name)

    def test_form_rejects_readonly_field(self):
        with self.assertRaises(schema.SchemaError):
            schema._resolve_field(SCREEN, {"field": "PAYDES"}, schema.load_catalog(SCREEN))


# ---------------------------------------------------------------------------
class ValidationTest(unittest.TestCase):
    """הוולידציה בשרת — היא שער הכניסה האמיתי לפריוריטי."""

    def validate(self, overrides=None, advanced=False):
        data = dict(VALID)
        data.update(overrides or {})
        return schema.validate_payload(SCREEN, data, include_advanced=advanced)

    def test_valid_payload_passes(self):
        _values, errors, _warnings = self.validate()
        self.assertEqual(errors, {})

    def test_missing_mandatory_is_error(self):
        _values, errors, _warnings = self.validate({"SUPDES": ""})
        self.assertIn("SUPDES", errors)

    def test_too_long_is_error(self):
        _values, errors, _warnings = self.validate({"SUPNAME": "X" * 17})
        self.assertIn("SUPNAME", errors)
        self.assertIn("16", errors["SUPNAME"])

    def test_max_length_edge_passes(self):
        _values, errors, _warnings = self.validate({"SUPNAME": "X" * 16})
        self.assertNotIn("SUPNAME", errors)

    def test_unknown_field_rejected(self):
        _values, errors, _warnings = self.validate({"DROP_TABLE": "1"})
        self.assertIn("DROP_TABLE", errors)

    def test_readonly_field_rejected(self):
        _values, errors, _warnings = self.validate({"PAYDES": "שוטף+30"})
        self.assertIn("PAYDES", errors)

    def test_boolean_words_normalised(self):
        values, errors, _warnings = self.validate({"CONFIDENTIAL": "כן"})
        self.assertEqual(errors, {})
        self.assertEqual(values["CONFIDENTIAL"], "Y")

    def test_boolean_rejects_free_text(self):
        _values, errors, _warnings = self.validate({"CONFIDENTIAL": "אולי"})
        self.assertIn("CONFIDENTIAL", errors)

    def test_integer_field_rejects_text(self):
        _values, errors, _warnings = self.validate({"SHIPMDAYS": "שבועיים"})
        self.assertIn("SHIPMDAYS", errors)

    def test_integer_field_rejects_fraction(self):
        _values, errors, _warnings = self.validate({"SHIPMDAYS": "3.5"})
        self.assertIn("SHIPMDAYS", errors)

    def test_date_formats_normalised(self):
        values, errors, _warnings = self.validate({"CREATEDDATE": "23/07/2026"})
        self.assertEqual(errors, {})
        self.assertEqual(values["CREATEDDATE"], "2026-07-23")

    def test_bad_date_is_error(self):
        _values, errors, _warnings = self.validate({"CREATEDDATE": "לא תאריך"})
        self.assertIn("CREATEDDATE", errors)

    def test_format_problems_are_warnings_not_errors(self):
        _values, errors, warnings = self.validate({"EMAIL": "not-an-email",
                                                   "PHONE": "123"})
        self.assertEqual(errors, {})
        self.assertIn("EMAIL", warnings)
        self.assertIn("PHONE", warnings)

    def test_transform_cleans_value(self):
        values, _errors, _warnings = self.validate({"SUPNAME": "  s 100 1 "})
        self.assertEqual(values["SUPNAME"], "s1001")

    def test_odata_body_types_and_skips_empty(self):
        values, errors, _warnings = self.validate({"SHIPMDAYS": "7",
                                                   "CREATEDDATE": "01/02/2026"})
        self.assertEqual(errors, {})
        body = schema.to_odata(SCREEN, values)
        self.assertEqual(body["SHIPMDAYS"], 7)
        self.assertEqual(body["CREATEDDATE"], "2026-02-01T00:00:00Z")
        self.assertNotIn("FAX", body)          # שדה ריק לא נשלח כלל
        self.assertEqual(body["SUPDES"], VALID["SUPDES"])


# ---------------------------------------------------------------------------
class SecurityTest(unittest.TestCase):
    def test_password_roundtrip(self):
        stored = security.hash_password("Sup3r-Secret")
        self.assertTrue(security.verify_password("Sup3r-Secret", stored))
        self.assertFalse(security.verify_password("sup3r-secret", stored))
        self.assertNotIn("Sup3r-Secret", stored)

    def test_password_policy(self):
        self.assertIsNotNone(security.password_problem("short1"))
        self.assertIsNotNone(security.password_problem("allletters"))
        self.assertIsNone(security.password_problem("Passw0rd-Long"))

    def test_secret_encryption_roundtrip(self):
        token = "E933543E0DB046F5A113E4C64D88E1EE"
        blob = security.encrypt_secret(token)
        self.assertTrue(blob.startswith("enc:"))
        self.assertNotIn(token, blob)
        self.assertEqual(security.decrypt_secret(blob), token)

    def test_tampered_secret_rejected(self):
        blob = security.encrypt_secret("hello")
        tampered = blob[:-4] + ("AAAA" if not blob.endswith("AAAA") else "BBBB")
        self.assertEqual(security.decrypt_secret(tampered), "")

    def test_phone_normalisation(self):
        for raw in ("0501234567", "050-123-4567", "+972501234567", "972501234567",
                    "00972501234567"):
            self.assertEqual(store.normalize_phone(raw), "+972501234567", raw)

    def test_phone_masking_hides_middle(self):
        masked = security.mask_phone("+972501234567")
        self.assertNotIn("1234", masked)
        self.assertTrue(masked.startswith("972"))

    def test_rate_limiter_blocks_after_limit(self):
        limiter = security.RateLimiter(limit=2, window_seconds=60)
        for _ in range(2):
            allowed, _wait = limiter.check("k")
            self.assertTrue(allowed)
            limiter.record("k")
        allowed, wait = limiter.check("k")
        self.assertFalse(allowed)
        self.assertGreater(wait, 0)


# ---------------------------------------------------------------------------
class OtpUnitTest(unittest.TestCase):
    def test_fingerprint_changes_with_data(self):
        one = otp.payload_fingerprint(SCREEN, VALID)
        two = otp.payload_fingerprint(SCREEN, dict(VALID, SUPDES="ספק אחר"))
        self.assertNotEqual(one, two)

    def test_fingerprint_is_order_independent(self):
        flipped = dict(reversed(list(VALID.items())))
        self.assertEqual(otp.payload_fingerprint(SCREEN, VALID),
                         otp.payload_fingerprint(SCREEN, flipped))

    def test_generated_code_shape(self):
        code = otp.generate_code()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

    def test_phone_policy_locks_to_user_number(self):
        user = {"id": 1, "phone": "+972501234567"}
        config = {"otp_phone_mode": "user"}
        self.assertEqual(otp.resolve_phone(user, "", config), "+972501234567")
        with self.assertRaises(otp.OtpError):
            otp.resolve_phone(user, "0529999999", config)

    def test_free_mode_allows_other_number(self):
        user = {"id": 1, "phone": "+972501234567"}
        config = {"otp_phone_mode": "free"}
        self.assertEqual(otp.resolve_phone(user, "052-9999999", config), "+972529999999")


# ---------------------------------------------------------------------------
class PriorityClientTest(unittest.TestCase):
    def test_pat_auth_header(self):
        client = priority.PriorityClient(url="https://h/odata/Priority/tabula.ini/demo",
                                         auth_method="token", token="ABC123")
        import base64
        expected = base64.b64encode(b"ABC123:PAT").decode()
        self.assertEqual(client.auth_header(), f"Basic {expected}")

    def test_bearer_auth_header(self):
        client = priority.PriorityClient(url="https://h/odata/Priority/tabula.ini/demo",
                                         auth_method="bearer", token="tok")
        self.assertEqual(client.auth_header(), "Bearer tok")

    def test_service_url_shape(self):
        self.assertTrue(priority.looks_like_service_url(
            "https://host6013.priority-guru.co.il/odata/Priority/tabula.ini/demo/"))
        self.assertFalse(priority.looks_like_service_url("https://host6013.example.com/"))

    def test_error_message_extracted_from_priority_json(self):
        raw = '{"error":{"code":"","message":{"value":"שדה חובה חסר: SUPDES"}}}'
        self.assertIn("SUPDES", priority.extract_priority_message(raw))

    def test_filter_escapes_quotes(self):
        self.assertEqual(priority._escape_odata("O'Brien"), "O''Brien")

    def test_metadata_properties_parsed(self):
        props = priority.parse_metadata_properties(METADATA_XML, "SUPPLIERS")
        self.assertEqual(props, {"SUPNAME", "SUPDES", "STATDES"})

    def test_metadata_unknown_entity_is_empty(self):
        self.assertEqual(priority.parse_metadata_properties(METADATA_XML, "ORDERS"), set())

    def test_metadata_bad_xml_raises_hebrew_error(self):
        with self.assertRaises(priority.PriorityError):
            priority.parse_metadata_properties("<not xml", "SUPPLIERS")


# $metadata מקוצר בסגנון פריוריטי — כולל namespace, כדי שהפרסור ייבדק כמו במציאות
METADATA_XML = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx" Version="4.0">
  <edmx:DataServices>
    <Schema xmlns="http://docs.oasis-open.org/odata/ns/edm" Namespace="Priority.OData">
      <EntityType Name="SUPPLIERS">
        <Key><PropertyRef Name="SUPNAME"/></Key>
        <Property Name="SUPNAME" Type="Edm.String"/>
        <Property Name="SUPDES" Type="Edm.String"/>
        <Property Name="STATDES" Type="Edm.String"/>
        <NavigationProperty Name="SUPPLIERSCONTACTS" Type="Collection(Priority.OData.X)"/>
      </EntityType>
      <EntityType Name="CUSTOMERS">
        <Property Name="CUSTNAME" Type="Edm.String"/>
      </EntityType>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>"""


# ---------------------------------------------------------------------------
class FakeClient:
    """כפיל של לקוח פריוריטי — מתעד קריאות ומחזיר תשובה מוכנה."""

    created = []
    existing = []
    fail_with = None

    def __init__(self, *_args, **_kwargs):
        pass

    def find(self, _entity, field, value, select=None, top=1):
        return [{field: value}] if value in FakeClient.existing else []

    def create(self, entity, body):
        if FakeClient.fail_with:
            raise priority.PriorityError(FakeClient.fail_with, status=400)
        FakeClient.created.append((entity, body))
        return dict(body, SUP=987)

    def test_connection(self, entity="SUPPLIERS"):
        return {"ok": True, "status": 200, "message": "ok", "sample_count": 1}

    def entity_properties(self, _entity):
        return set(FakeClient.properties)

    # ברירת מחדל: פריוריטי מכיר את כל שדות הטופס
    properties = []


class FlowTest(unittest.TestCase):
    """מסלול מלא דרך ה-HTTP: התחברות, ולידציה, OTP וטעינה."""

    @classmethod
    def setUpClass(cls):
        webapp.app.config["TESTING"] = True
        store.init(force=True)
        for user in store.list_users():
            store.delete_user(user["id"])
        store.create_user("admin", "Passw0rd-Long", "מנהל", "0501234567", "admin")
        store.set_config({
            "priority_url": "https://host/odata/Priority/tabula.ini/demo",
            "priority_auth": "token",
            "priority_token_secret": "TOKEN",
            "otp_channel": "console",
            "otp_phone_mode": "user",
        })

    def setUp(self):
        FakeClient.created = []
        FakeClient.existing = []
        FakeClient.fail_with = None
        self._real_client = views.client_from_config
        views.client_from_config = lambda _config: FakeClient()
        self.client = webapp.app.test_client()
        # מגבלות הקצב הן לכל התהליך — איפוס כדי שבדיקות לא ישפיעו זו על זו
        otp.send_limiter._hits.clear()
        otp.verify_limiter._hits.clear()
        auth.login_limiter._hits.clear()

    def tearDown(self):
        views.client_from_config = self._real_client

    # -- עזרים --
    def login(self, username="admin", password="Passw0rd-Long"):
        page = self.client.get("/intake/login")
        token = self._csrf(page.data.decode())
        return self.client.post("/intake/login", data={
            "username": username, "password": password, "csrf_token": token,
        }, follow_redirects=False)

    @staticmethod
    def _csrf(html):
        import re
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        return match.group(1) if match else ""

    def post_json(self, path, body):
        with self.client.session_transaction() as session:
            token = session.get("intake_csrf", "")
        return self.client.post(path, json=body, headers={"X-CSRF-Token": token})

    def send_and_verify_otp(self, values):
        response = self.post_json("/intake/api/otp/send", {"values": values})
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        code = payload["dev_code"]
        verify = self.post_json("/intake/api/otp/verify",
                                {"otp_id": payload["otp_id"], "code": code, "values": values})
        self.assertEqual(verify.status_code, 200, verify.get_json())
        return payload["otp_id"]

    # -- בדיקות --
    def test_pages_require_login(self):
        for path in ("/intake/", "/intake/new", "/intake/history", "/intake/settings"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302, path)
            self.assertIn("/intake/login", response.headers["Location"], path)

    def test_api_requires_login(self):
        response = self.client.post("/intake/api/submit", json={})
        self.assertIn(response.status_code, (400, 401))

    def test_bad_password_rejected(self):
        response = self.login(password="wrong-password-1")
        self.assertEqual(response.status_code, 200)     # נשאר במסך ההתחברות
        self.assertIn("שגויים", response.data.decode())

    def test_csrf_required_on_api(self):
        self.login()
        response = self.client.post("/intake/api/validate", json={"values": VALID})
        self.assertEqual(response.status_code, 400)

    def test_full_intake_flow(self):
        self.login()
        response = self.post_json("/intake/api/validate", {"values": VALID})
        self.assertTrue(response.get_json()["ok"])

        otp_id = self.send_and_verify_otp(VALID)
        response = self.post_json("/intake/api/submit", {"otp_id": otp_id, "values": VALID})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["key"], "S1001")

        entity, body = FakeClient.created[0]
        self.assertEqual(entity, "SUPPLIERS")
        self.assertEqual(body["SUPDES"], VALID["SUPDES"])
        self.assertEqual(body["STATDES"], "פעיל")

        rows = store.list_submissions(limit=1)
        self.assertEqual(rows[0]["status"], "created")
        self.assertNotIn("1234", rows[0]["phone"])       # הטלפון מוסתר ביומן

    def test_submit_without_otp_is_blocked(self):
        self.login()
        response = self.post_json("/intake/api/submit", {"values": VALID})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.get_json()["need_otp"])
        self.assertEqual(FakeClient.created, [])

    def test_otp_cannot_be_reused_for_another_supplier(self):
        self.login()
        otp_id = self.send_and_verify_otp(VALID)
        other = dict(VALID, SUPNAME="S2002", SUPDES="ספק אחר לגמרי")
        response = self.post_json("/intake/api/submit", {"otp_id": otp_id, "values": other})
        self.assertEqual(response.status_code, 400)
        self.assertIn("השתנו", response.get_json()["error"])
        self.assertEqual(FakeClient.created, [])

    def test_otp_is_single_use(self):
        self.login()
        otp_id = self.send_and_verify_otp(VALID)
        first = self.post_json("/intake/api/submit", {"otp_id": otp_id, "values": VALID})
        self.assertEqual(first.status_code, 200)
        second = self.post_json("/intake/api/submit", {"otp_id": otp_id, "values": VALID})
        self.assertEqual(second.status_code, 400)
        self.assertEqual(len(FakeClient.created), 1)

    def test_otp_claim_is_atomic(self):
        """שתי טעינות במקביל עם אותו קוד — רק אחת תופסת אותו."""
        self.login()
        otp_id = self.send_and_verify_otp(VALID)
        self.assertTrue(store.claim_otp(otp_id))
        self.assertFalse(store.claim_otp(otp_id))
        store.release_otp(otp_id)
        self.assertTrue(store.claim_otp(otp_id))

    def test_failed_load_releases_the_code(self):
        """כשפריוריטי דוחה — לא נוצר ספק, ולכן הקוד נשאר תקף לניסיון נוסף."""
        self.login()
        otp_id = self.send_and_verify_otp(VALID)
        FakeClient.fail_with = "תקלה זמנית"
        self.assertEqual(
            self.post_json("/intake/api/submit", {"otp_id": otp_id, "values": VALID}).status_code,
            502)
        FakeClient.fail_with = None
        retry = self.post_json("/intake/api/submit", {"otp_id": otp_id, "values": VALID})
        self.assertEqual(retry.status_code, 200, retry.get_json())
        self.assertEqual(len(FakeClient.created), 1)

    def test_wrong_otp_code_rejected(self):
        self.login()
        response = self.post_json("/intake/api/otp/send", {"values": VALID})
        payload = response.get_json()
        wrong = "000000" if payload["dev_code"] != "000000" else "111111"
        verify = self.post_json("/intake/api/otp/verify",
                                {"otp_id": payload["otp_id"], "code": wrong, "values": VALID})
        self.assertEqual(verify.status_code, 400)
        self.assertIn("שגוי", verify.get_json()["error"])

    def test_otp_not_sent_when_data_invalid(self):
        self.login()
        response = self.post_json("/intake/api/otp/send",
                                  {"values": dict(VALID, SUPDES="")})
        self.assertEqual(response.status_code, 400)
        self.assertIn("SUPDES", response.get_json()["errors"])

    def test_duplicate_supplier_blocked(self):
        self.login()
        FakeClient.existing = ["S1001"]
        otp_id = self.send_and_verify_otp(VALID)
        response = self.post_json("/intake/api/submit", {"otp_id": otp_id, "values": VALID})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(FakeClient.created, [])

    def test_priority_error_is_logged_and_reported(self):
        self.login()
        FakeClient.fail_with = "שדה חובה חסר בפריוריטי"
        otp_id = self.send_and_verify_otp(VALID)
        response = self.post_json("/intake/api/submit", {"otp_id": otp_id, "values": VALID})
        self.assertEqual(response.status_code, 502)
        self.assertIn("חובה", response.get_json()["error"])
        self.assertEqual(store.list_submissions(limit=1)[0]["status"], "failed")

    def test_non_admin_cannot_reach_settings(self):
        store.create_user("clerk", "Passw0rd-Long", "פקיד", "0521234567", "user")
        self.login("clerk", "Passw0rd-Long")
        response = self.client.get("/intake/settings")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/intake/"))

    def test_wizard_page_renders_all_mandatory_fields(self):
        self.login()
        html = self.client.get("/intake/new").data.decode()
        for name in ("SUPDES", "STATDES", "OWNERLOGIN", "CODE",
                     "ERPG_SECNAME", "ERPG_TRIALBALCODE"):
            self.assertIn(f'data-field="{name}"', html)

    def test_field_check_passes_when_priority_knows_every_field(self):
        self.login()
        FakeClient.properties = list(schema.form_fields(SCREEN, include_advanced=True))
        result = self.post_json("/intake/api/check-fields", {}).get_json()
        self.assertTrue(result["ok"], result.get("missing"))
        self.assertEqual(result["missing"], [])

    def test_field_check_reports_fields_priority_does_not_have(self):
        self.login()
        known = list(schema.form_fields(SCREEN, include_advanced=True))
        FakeClient.properties = [n for n in known if n not in ("SUPTYPECODE", "GPSX")]
        result = self.post_json("/intake/api/check-fields", {}).get_json()
        self.assertFalse(result["ok"])
        self.assertEqual({f["name"] for f in result["missing"]}, {"SUPTYPECODE", "GPSX"})

    def test_field_check_is_admin_only(self):
        store.create_user("clerk2", "Passw0rd-Long", "פקיד", "0521234567", "user")
        self.login("clerk2", "Passw0rd-Long")
        self.assertEqual(self.post_json("/intake/api/check-fields", {}).status_code, 403)

    def test_removed_field_is_gone_from_the_form(self):
        """FOREIGN אינו קיים ב-OData של פריוריטי — אסור שיישלח."""
        self.assertNotIn("FOREIGN", schema.form_fields(SCREEN, include_advanced=True))

    def test_settings_page_never_echoes_the_token(self):
        self.login()
        html = self.client.get("/intake/settings").data.decode()
        self.assertNotIn("TOKEN", html)

    def test_file_loader_login_untouched_by_intake(self):
        """הממשק החדש לא פותח דלת אחורית לכלי הקיים."""
        self.assertTrue(webapp.app.url_map.bind("x").match("/intake/")[0].startswith("intake."))


if __name__ == "__main__":
    unittest.main(verbosity=2)
