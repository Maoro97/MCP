-- =====================================================================
-- PensionOS · Migration 0003 · נתוני ייחוס
--
-- ⚠️ הערכים כאן הם נקודת פתיחה לפיתוח. לפני Go-Live כל רשומה עם
--    source_ref = 'PENDING_VERIFICATION' חייבת אימות מול הנוסח העדכני
--    של החוזר/התקנה, ואישור יועץ הציות. הבדיקה בסוף הקובץ תזהיר על כל
--    רשומה שנותרה לא-מאומתת.
-- =====================================================================

BEGIN;

-- --- יצרנים ------------------------------------------------------------
-- ⚠️ הקודים הם placeholders. הקודים הרשמיים יטענו מרשימת הגופים
--    המוסדיים של רשות שוק ההון ב-Sprint 0.
INSERT INTO clearing.providers (code, name_he, provider_type) VALUES
  ('520023185', 'מנורה מבטחים',  'insurer'),
  ('520026445', 'כלל ביטוח',      'insurer'),
  ('520033613', 'הראל',           'insurer'),
  ('520023096', 'הפניקס',         'insurer'),
  ('520042177', 'מגדל',           'insurer'),
  ('513173393', 'אלטשולר שחם',    'investment_house'),
  ('511016776', 'מיטב',           'investment_house'),
  ('520037582', 'פסגות',          'investment_house'),
  ('999999999', 'יצרן לבדיקות',   'investment_house')
ON CONFLICT (code) DO NOTHING;

-- --- פרמטרים רגולטוריים -------------------------------------------------
-- מנוהלים כ-DATA: שינוי תקרה רגולטורית הוא INSERT, לא Deploy.
-- מנוע החוקים תמיד קורא את הרשומה שבתוקף לתאריך ההמלצה.
INSERT INTO reco.regulatory_params
  (param_key, param_value, source_ref, effective_from, version) VALUES

  ('fee_cap.pension_comprehensive',
   '{"deposit_pct": 6.0, "balance_pct": 0.5}'::jsonb,
   'PENDING_VERIFICATION: תקנות קופות גמל (דמי ניהול)', '2024-01-01', 'draft-1'),

  ('fee_cap.provident_fund',
   '{"deposit_pct": 4.0, "balance_pct": 1.05}'::jsonb,
   'PENDING_VERIFICATION: תקנות קופות גמל (דמי ניהול)', '2024-01-01', 'draft-1'),

  ('fee_cap.managers_insurance',
   '{"deposit_pct": 4.0, "balance_pct": 1.05}'::jsonb,
   'PENDING_VERIFICATION: תקנות קופות גמל (דמי ניהול)', '2024-01-01', 'draft-1'),

  ('fee_cap.study_fund',
   '{"deposit_pct": 0.0, "balance_pct": 2.0}'::jsonb,
   'PENDING_VERIFICATION: תקנות קופות גמל (דמי ניהול)', '2024-01-01', 'draft-1'),

  -- סף השנה שממנה בוטלו מקדמי הקצבה המובטחים בפוליסות חדשות.
  -- מזין את R-PEN-001, חוק חוסם.
  ('guaranteed_factor.cutoff_date',
   '{"date": "2013-01-01"}'::jsonb,
   'PENDING_VERIFICATION: חוזר רשות שוק ההון', '2013-01-01', 'draft-1'),

  -- יחס כיסוי א.כ.ע מומלץ מהשכר — משמש להצגת פער בתיק 360°
  ('coverage.disability_target_ratio',
   '{"ratio": 0.75}'::jsonb,
   'INTERNAL: כלל אצבע מקצועי, אינו דרישה רגולטורית', '2024-01-01', 'draft-1')

ON CONFLICT (param_key, effective_from) DO NOTHING;

-- --- קטלוג חוקי הסיכון --------------------------------------------------
-- החוקים עצמם (התנאים ב-JSONLogic) נטענים ע"י שירות ההמלצות ב-E6.
-- כאן נרשמת רק הרשומה הרגולטורית שמסבירה כל חוק, לצורך המסמך והביקורת.
CREATE TABLE IF NOT EXISTS reco.rule_catalog (
  rule_id        TEXT PRIMARY KEY,
  title_he       TEXT NOT NULL,
  severity       TEXT NOT NULL CHECK (severity IN
                 ('info','warning','critical','blocker')),
  rationale_he   TEXT NOT NULL,
  requires_client_ack BOOLEAN NOT NULL DEFAULT false,
  source_ref     TEXT NOT NULL,
  version        TEXT NOT NULL,
  effective_from DATE NOT NULL DEFAULT CURRENT_DATE
);

INSERT INTO reco.rule_catalog
  (rule_id, title_he, severity, rationale_he, requires_client_ack, source_ref, version) VALUES
  ('R-PEN-001', 'ניוד מפוליסה עם מקדם קצבה מובטח', 'blocker',
   'ניוד הכספים יבטל את מקדם הקצבה המובטח ויקטין את הקצבה החודשית הצפויה. '
   'נדרש נימוק מפורש והצהרת לקוח נפרדת.', true,
   'PENDING_VERIFICATION', 'draft-1'),
  ('R-PEN-002', 'ניוד מקרן פנסיה ותיקה', 'blocker',
   'ניוד מקרן ותיקה כרוך באובדן זכויות שאינן ניתנות לשחזור.', true,
   'PENDING_VERIFICATION', 'draft-1'),
  ('R-INS-003', 'ביטול או הקטנת כיסוי אובדן כושר עבודה', 'critical',
   'רכישת כיסוי חלופי כפופה לחיתום רפואי מחדש ולתקופת אכשרה.', true,
   'PENDING_VERIFICATION', 'draft-1'),
  ('R-INS-004', 'קיום מצב רפואי קודם או החרגה', 'critical',
   'החלפת פוליסה עלולה להותיר את המצב הרפואי הקיים ללא כיסוי.', true,
   'PENDING_VERIFICATION', 'draft-1'),
  ('R-INS-005', 'החלפת פוליסה בעלת תנאי דור קודם', 'warning',
   'לפוליסה הקיימת תנאים שאינם קיימים במוצרים הנמכרים היום.', false,
   'PENDING_VERIFICATION', 'draft-1'),
  ('R-FEE-006', 'דמי הניהול המוצעים אינם נמוכים מהקיימים', 'warning',
   'ההמלצה אינה משפרת את דמי הניהול, ולכן נדרש נימוק שאינו כלכלי-ישיר.', false,
   'INTERNAL', 'draft-1'),
  ('R-FEE-007', 'חריגה מתקרת דמי ניהול', 'blocker',
   'דמי הניהול המוצעים חורגים מהתקרה הרגולטורית.', false,
   'PENDING_VERIFICATION', 'draft-1'),
  ('R-DAT-008', 'נתון חובה חסר במוצר שנכלל בהמלצה', 'blocker',
   'לא ניתן להפיק מסמך הנמקה על בסיס נתונים חלקיים.', false,
   'INTERNAL', 'draft-1'),
  ('R-BEN-009', 'אין מוטבים מעודכנים', 'info',
   'מומלץ לעדכן מוטבים בקופה המומלצת.', false,
   'INTERNAL', 'draft-1')
ON CONFLICT (rule_id) DO NOTHING;

COMMIT;

-- --- אזהרת ציות ---------------------------------------------------------
DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n FROM reco.regulatory_params
   WHERE source_ref LIKE 'PENDING_VERIFICATION%';
  IF n > 0 THEN
    RAISE WARNING
      '% פרמטרים רגולטוריים טרם אומתו מול הרגולציה. חובה לאמת לפני Go-Live.', n;
  END IF;
END $$;
