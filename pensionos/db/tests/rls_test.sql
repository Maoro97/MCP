-- =====================================================================
-- בדיקת בידוד Tenant — רצה ב-CI וחוסמת merge.
--
-- הבדיקות מתבצעות בתפקיד שאינו superuser וללא BYPASSRLS, כי superuser
-- עוקף RLS תמיד — בדיקה שרצה כ-postgres תעבור גם כשההגנה שבורה לגמרי.
--
-- הרצה:  psql -d pensionos -v ON_ERROR_STOP=1 -f db/tests/rls_test.sql
-- =====================================================================

\set ON_ERROR_STOP on
\pset pager off

-- --- הכנה (כ-superuser) ----------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rls_tester') THEN
    CREATE ROLE rls_tester LOGIN NOBYPASSRLS IN ROLE pensionos_app;
  END IF;
END $$;

GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA
  identity, clients, clearing, portfolio, reco, docs, sign TO rls_tester;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA audit TO rls_tester;
GRANT USAGE ON SCHEMA identity, clients, clearing, portfolio, reco, docs, sign, audit
  TO rls_tester;

TRUNCATE portfolio.snapshots, clients.clients, identity.users, identity.tenants CASCADE;

INSERT INTO identity.tenants (id, legal_name, license_number, tax_id, kms_key_arn)
VALUES
  ('11111111-1111-1111-1111-111111111111', 'סוכנות אלף', 'LIC-001', '510000001', 'arn:a'),
  ('22222222-2222-2222-2222-222222222222', 'סוכנות בית', 'LIC-002', '510000002', 'arn:b');

INSERT INTO identity.users (id, tenant_id, cognito_sub, full_name, email, role)
VALUES
  ('aaaaaaaa-0000-0000-0000-000000000001',
   '11111111-1111-1111-1111-111111111111', 'sub-a1', 'דני סוכן', 'a1@x.co.il', 'agent'),
  ('aaaaaaaa-0000-0000-0000-000000000002',
   '11111111-1111-1111-1111-111111111111', 'sub-a2', 'מיכל מנהלת', 'a2@x.co.il', 'agency_admin'),
  ('bbbbbbbb-0000-0000-0000-000000000001',
   '22222222-2222-2222-2222-222222222222', 'sub-b1', 'רון סוכן', 'b1@y.co.il', 'agent');

INSERT INTO clients.clients
  (id, tenant_id, owner_user_id, national_id_enc, national_id_hash,
   national_id_last4, first_name, last_name)
VALUES
  ('cccccccc-0000-0000-0000-00000000000a',
   '11111111-1111-1111-1111-111111111111', 'aaaaaaaa-0000-0000-0000-000000000001',
   '\x01', '\xaa', '2519', 'דנה', 'כהן'),
  ('cccccccc-0000-0000-0000-00000000000b',
   '11111111-1111-1111-1111-111111111111', 'aaaaaaaa-0000-0000-0000-000000000002',
   '\x02', '\xbb', '4562', 'אורי', 'לוי'),
  ('cccccccc-0000-0000-0000-00000000000c',
   '22222222-2222-2222-2222-222222222222', 'bbbbbbbb-0000-0000-0000-000000000001',
   '\x03', '\xcc', '6678', 'שירה', 'מזרחי');

-- --- מכאן והלאה: תפקיד ללא הרשאות-על ---------------------------------
SET ROLE rls_tester;

\echo '── 1. שלמות ה-RLS: כל טבלה עם tenant_id מוגנת'
DO $$
DECLARE bad int;
BEGIN
  SELECT count(*) INTO bad FROM audit.assert_rls_complete();
  IF bad > 0 THEN
    RAISE EXCEPTION 'FAIL: % טבלאות ללא הגנת RLS מלאה', bad;
  END IF;
  RAISE NOTICE 'PASS: כל הטבלאות מוגנות';
END $$;

\echo '── 2. ללא הקשר tenant — לא נראה כלום'
DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n FROM clients.clients;
  IF n <> 0 THEN
    RAISE EXCEPTION 'FAIL: נחשפו % לקוחות ללא הקשר tenant', n;
  END IF;
  RAISE NOTICE 'PASS: 0 שורות ללא הקשר';
END $$;

\echo '── 3. מנהלת סוכנות א רואה את שני הלקוחות של סוכנות א בלבד'
DO $$
DECLARE n int;
BEGIN
  PERFORM set_config('app.current_tenant', '11111111-1111-1111-1111-111111111111', true);
  PERFORM set_config('app.current_user',   'aaaaaaaa-0000-0000-0000-000000000002', true);
  PERFORM set_config('app.current_role',   'agency_admin', true);

  SELECT count(*) INTO n FROM clients.clients;
  IF n <> 2 THEN RAISE EXCEPTION 'FAIL: צפוי 2, התקבל %', n; END IF;

  -- גישה ישירה למזהה של סוכנות אחרת (IDOR)
  SELECT count(*) INTO n FROM clients.clients
   WHERE id = 'cccccccc-0000-0000-0000-00000000000c';
  IF n <> 0 THEN RAISE EXCEPTION 'FAIL: דליפת מידע בין סוכנויות!'; END IF;

  RAISE NOTICE 'PASS: בידוד בין סוכנויות תקין';
END $$;

\echo '── 4. סוכן רגיל רואה רק את הלקוחות שבטיפולו'
DO $$
DECLARE n int;
BEGIN
  PERFORM set_config('app.current_tenant', '11111111-1111-1111-1111-111111111111', true);
  PERFORM set_config('app.current_user',   'aaaaaaaa-0000-0000-0000-000000000001', true);
  PERFORM set_config('app.current_role',   'agent', true);

  SELECT count(*) INTO n FROM clients.clients;
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL: צפוי 1, התקבל %', n; END IF;

  SELECT count(*) INTO n FROM clients.clients
   WHERE id = 'cccccccc-0000-0000-0000-00000000000b';
  IF n <> 0 THEN RAISE EXCEPTION 'FAIL: סוכן ראה לקוח של סוכן אחר'; END IF;

  RAISE NOTICE 'PASS: היקף הסוכן תקין';
END $$;

\echo '── 5. אי אפשר לכתוב שורה לסוכנות אחרת'
DO $$
BEGIN
  PERFORM set_config('app.current_tenant', '11111111-1111-1111-1111-111111111111', true);
  PERFORM set_config('app.current_role',   'agency_admin', true);
  BEGIN
    INSERT INTO clients.clients
      (tenant_id, national_id_enc, national_id_hash, national_id_last4,
       first_name, last_name)
    VALUES ('22222222-2222-2222-2222-222222222222',
            '\x09', '\x99', '0000', 'זדוני', 'ניסיון');
    RAISE EXCEPTION 'FAIL: הצלחנו לכתוב לסוכנות אחרת!';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'PASS: כתיבה חוצת-סוכנות נחסמה';
  END;
END $$;

\echo '── 6. Snapshot בלתי-משתנה'
DO $$
DECLARE v text; n int;
BEGIN
  PERFORM set_config('app.current_tenant', '11111111-1111-1111-1111-111111111111', true);
  PERFORM set_config('app.current_role',   'agency_admin', true);

  INSERT INTO portfolio.snapshots
    (id, tenant_id, client_id, created_by, payload, payload_sha256,
     parser_version, mapping_version)
  VALUES ('dddddddd-0000-0000-0000-00000000000a',
          '11111111-1111-1111-1111-111111111111',
          'cccccccc-0000-0000-0000-00000000000a',
          'aaaaaaaa-0000-0000-0000-000000000001',
          '{"products":[{"balance":842100.55}]}'::jsonb, '\xdeadbeef',
          '1.0.0', '2026.03');

  UPDATE portfolio.snapshots SET payload = '{"products":[]}'::jsonb
   WHERE id = 'dddddddd-0000-0000-0000-00000000000a';

  SELECT payload::text INTO v FROM portfolio.snapshots
   WHERE id = 'dddddddd-0000-0000-0000-00000000000a';
  IF v = '{"products": []}' THEN
    RAISE EXCEPTION 'FAIL: Snapshot שונה לאחר יצירתו!';
  END IF;

  DELETE FROM portfolio.snapshots WHERE id = 'dddddddd-0000-0000-0000-00000000000a';
  SELECT count(*) INTO n FROM portfolio.snapshots
   WHERE id = 'dddddddd-0000-0000-0000-00000000000a';
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL: Snapshot נמחק!'; END IF;

  RAISE NOTICE 'PASS: Snapshot חסין לשינוי ולמחיקה';
END $$;

\echo '── 7. אודיט append-only'
DO $$
DECLARE n int;
BEGIN
  PERFORM set_config('app.current_tenant', '11111111-1111-1111-1111-111111111111', true);
  INSERT INTO audit.logs (tenant_id, action, entity_type, client_id)
  VALUES ('11111111-1111-1111-1111-111111111111', 'READ', 'client',
          'cccccccc-0000-0000-0000-00000000000a');

  DELETE FROM audit.logs;
  SELECT count(*) INTO n FROM audit.logs;
  IF n = 0 THEN RAISE EXCEPTION 'FAIL: רשומות אודיט נמחקו!'; END IF;

  RAISE NOTICE 'PASS: האודיט חסין למחיקה';
END $$;

\echo '── 8. אילוץ רגולטורי: סירוב למסור מידע מחייב תיעוד ההשפעה'
DO $$
BEGIN
  PERFORM set_config('app.current_tenant', '11111111-1111-1111-1111-111111111111', true);
  BEGIN
    INSERT INTO reco.recommendations
      (tenant_id, client_id, snapshot_id, agent_id, client_declined_info,
       rules_version, reg_params_version)
    VALUES ('11111111-1111-1111-1111-111111111111',
            'cccccccc-0000-0000-0000-00000000000a',
            'dddddddd-0000-0000-0000-00000000000a',
            'aaaaaaaa-0000-0000-0000-000000000001',
            true, 'r1', 'p1');
    RAISE EXCEPTION 'FAIL: התקבלה המלצה ללא תיעוד השפעת אי-מסירת המידע';
  EXCEPTION WHEN check_violation THEN
    RAISE NOTICE 'PASS: האילוץ הרגולטורי נאכף';
  END;
END $$;

RESET ROLE;
\echo ''
\echo '✔ כל בדיקות בידוד ה-Tenant עברו'
