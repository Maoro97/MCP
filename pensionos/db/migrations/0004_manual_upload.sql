-- =====================================================================
-- PensionOS · Migration 0004 · התאמות שנגזרו מהמימוש
--
-- שני תיקוני מודל שהתגלו כשחיברנו את מנוע הפענוח למסד הנתונים.
-- =====================================================================

BEGIN;

-- 1. קליטה ידנית של קובץ אינה "בקשה למסלקה".
--    עד שהאינטגרציה למסלקה (E3) תיבנה, ואחריה עבור קבצים שהלקוח מביא
--    בעצמו, יש קבצים ללא request_id. הכפייה על שיוך לבקשה הייתה מאלצת
--    אותנו להמציא בקשה מזויפת — ולזהם את נתוני העלויות והאודיט.
ALTER TABLE clearing.files
  ALTER COLUMN request_id DROP NOT NULL,
  ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'clearing'
    CHECK (source IN ('clearing','manual_upload')),
  ADD COLUMN IF NOT EXISTS client_id UUID REFERENCES clients.clients(id),
  ADD CONSTRAINT files_source_consistency CHECK (
    (source = 'clearing'      AND request_id IS NOT NULL) OR
    (source = 'manual_upload' AND client_id  IS NOT NULL)
  );

-- 2. תאריך נכונות הנתונים חסר בפועל אצל חלק מהיצרנים.
--    NOT NULL היה מאלץ אותנו לבחור בין להמציא תאריך לבין לזרוק את המוצר.
--    שניהם גרועים: המצאה מזייפת נתון שמוצג ללקוח, וזריקה מסתירה נכס קיים.
--    הנכון הוא להציג "— לא התקבל", וזה בדיוק מה ש-NULL אומר.
ALTER TABLE portfolio.products
  ALTER COLUMN report_date DROP NOT NULL;

COMMENT ON COLUMN portfolio.products.report_date IS
  'NULL = היצרן לא דיווח. מוצג כ"לא התקבל" ומייצר חריג חוסם להנמקה.';

COMMIT;
