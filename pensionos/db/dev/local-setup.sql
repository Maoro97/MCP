-- =====================================================================
-- הכנת סביבת פיתוח מקומית.
--
-- ⚠️ לפיתוח בלבד — סיסמה קבועה בקוד. בייצור החיבור מתבצע ב-IAM Auth
--    מול Aurora, ללא סיסמה כלל.
--
-- הנקודה החשובה: תפקיד ה-API יורש מ-pensionos_app ולכן **אינו** superuser
-- ואין לו BYPASSRLS. ה-API מסרב לעלות אם זה לא המצב.
-- =====================================================================

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pensionos_api') THEN
    CREATE ROLE pensionos_api LOGIN PASSWORD 'devpass' NOBYPASSRLS
      IN ROLE pensionos_app;
  END IF;
END $$;

GRANT USAGE ON SCHEMA identity, clients, clearing, portfolio, reco, docs, sign, audit
  TO pensionos_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA
  clients, clearing, portfolio, reco, docs, sign TO pensionos_api;
GRANT SELECT ON ALL TABLES IN SCHEMA identity TO pensionos_api;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA audit TO pensionos_api;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA
  clearing, sign, audit, portfolio TO pensionos_api;

-- מחיקה מותרת רק במקומות שבהם החלפה מלאה היא ההתנהגות הנכונה
-- (כיסויים ומוטבים — תמונת מצב של הדיווח האחרון).
REVOKE DELETE ON portfolio.products, portfolio.snapshots FROM pensionos_api;

-- סוכנות ומשתמש לדוגמה
INSERT INTO identity.tenants (id, legal_name, license_number, tax_id, kms_key_arn)
VALUES ('11111111-1111-1111-1111-111111111111',
        'סוכנות הדגמה בע"מ', 'LIC-DEMO-01', '515000001', 'arn:local:dev')
ON CONFLICT (id) DO NOTHING;

INSERT INTO identity.users (id, tenant_id, cognito_sub, full_name, email, role, mfa_enabled)
VALUES ('aaaaaaaa-0000-0000-0000-000000000001',
        '11111111-1111-1111-1111-111111111111',
        'dev-sub-1', 'דני סוכן', 'dani@demo.co.il', 'agency_admin', true)
ON CONFLICT (id) DO NOTHING;

\echo ''
\echo 'סביבת פיתוח מוכנה:'
\echo '  tenantId = 11111111-1111-1111-1111-111111111111'
\echo '  userId   = aaaaaaaa-0000-0000-0000-000000000001'
