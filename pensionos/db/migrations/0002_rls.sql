-- =====================================================================
-- PensionOS · Migration 0002 · בידוד Tenant ברמת מסד הנתונים
--
-- ה-Guards של NestJS הם שכבת ההגנה הראשונה. RLS היא רשת הביטחון: באג
-- בשאילתה, endpoint שנשכח, או SQL ידני של מפתח — כולם עדיין נחסמים.
--
-- הפוליסות נוצרות בלולאה על כל טבלה שיש בה tenant_id, כדי שאי אפשר יהיה
-- "לשכוח" טבלה. פונקציית האימות בסוף הקובץ היא הבדיקה החוסמת ב-CI.
-- =====================================================================

BEGIN;

-- תפקיד האפליקציה: ללא BYPASSRLS, ללא SUPERUSER, ללא הרשאת מחיקה באודיט
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pensionos_app') THEN
    CREATE ROLE pensionos_app NOLOGIN NOBYPASSRLS;
  END IF;
END $$;

GRANT USAGE ON SCHEMA identity, clients, clearing, portfolio, reco, docs, sign, audit
  TO pensionos_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA
  identity, clients, clearing, portfolio, reco, docs, sign TO pensionos_app;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA audit TO pensionos_app;  -- append-only
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA
  clearing, sign, audit, portfolio TO pensionos_app;

-- מחיקה מותרת רק דרך תהליך ה-Retention, שרץ בתפקיד נפרד
REVOKE DELETE ON ALL TABLES IN SCHEMA audit FROM pensionos_app;

-- ---------------------------------------------------------------------
-- פוליסת בידוד גורפת לכל טבלה עם tenant_id
-- ---------------------------------------------------------------------
DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT c.table_schema AS s, c.table_name AS t
    FROM information_schema.columns c
    JOIN information_schema.tables tb
      ON tb.table_schema = c.table_schema AND tb.table_name = c.table_name
    WHERE c.column_name = 'tenant_id'
      AND tb.table_type = 'BASE TABLE'
      AND c.table_schema IN ('identity','clients','clearing','portfolio',
                             'reco','docs','sign','audit')
  LOOP
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', r.s, r.t);
    -- FORCE — הפוליסה חלה גם על בעל הטבלה עצמו
    EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY', r.s, r.t);
    EXECUTE format($f$
      CREATE POLICY tenant_isolation ON %I.%I
        USING (tenant_id = app_tenant())
        WITH CHECK (tenant_id = app_tenant())
    $f$, r.s, r.t);
  END LOOP;
END $$;

-- טבלת ה-tenants עצמה: כל tenant רואה רק את עצמו
ALTER TABLE identity.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE identity.tenants FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_self ON identity.tenants
  USING (id = app_tenant())
  WITH CHECK (id = app_tenant());

-- ---------------------------------------------------------------------
-- שכבה שנייה: סוכן רגיל רואה רק את הלקוחות שבטיפולו.
-- agency_admin ו-compliance רואים את כל הסוכנות.
-- ---------------------------------------------------------------------
CREATE POLICY agent_scope ON clients.clients
  AS RESTRICTIVE
  USING (
    app_role() IN ('agency_admin','compliance','support')
    OR owner_user_id = app_user()
    OR owner_user_id IS NULL
  );

-- ---------------------------------------------------------------------
-- אכיפת append-only על האודיט: גם מי שקיבל בטעות הרשאת UPDATE לא ישנה
-- רשומה קיימת.
-- ---------------------------------------------------------------------
CREATE RULE audit_no_update AS ON UPDATE TO audit.logs DO INSTEAD NOTHING;
CREATE RULE audit_no_delete AS ON DELETE TO audit.logs DO INSTEAD NOTHING;

-- ---------------------------------------------------------------------
-- בדיקת CI חוסמת: כל טבלה עם tenant_id חייבת RLS כפוי + פוליסה.
-- מיגרציה שמוסיפה טבלה בלי הגנה תיכשל כאן, לא בייצור.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION audit.assert_rls_complete()
RETURNS TABLE (schema_name text, table_name text, problem text)
LANGUAGE sql STABLE AS $$
  SELECT n.nspname::text, c.relname::text,
         CASE
           WHEN NOT c.relrowsecurity THEN 'RLS לא מופעל'
           WHEN NOT c.relforcerowsecurity THEN 'RLS לא כפוי (FORCE חסר)'
           ELSE 'אין פוליסת בידוד'
         END
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id'
                      AND NOT a.attisdropped
  WHERE c.relkind = 'r'
    AND n.nspname IN ('identity','clients','clearing','portfolio',
                      'reco','docs','sign','audit')
    AND (
      NOT c.relrowsecurity
      OR NOT c.relforcerowsecurity
      OR NOT EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid)
    );
$$;
COMMENT ON FUNCTION audit.assert_rls_complete() IS
  'מחזירה שורות = כשל. ה-CI מריץ ומצפה ל-0 שורות.';

COMMIT;
