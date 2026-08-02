# PensionOS

פלטפורמת SaaS לסוכני ביטוח ופנסיה בישראל.
המפרט המלא: [`../docs/insurance-agent-saas/`](../docs/insurance-agent-saas/README.md)

---

## מה קיים בקוד כרגע

**Increment 1** — מנוע קליטה ופענוח + שכבת הנתונים (E4 + חלק מ-E0).
**Increment 2** — API ותיק לקוח 360° (E5 + חלק מ-E0/E2).

| רכיב | מיקום | סטטוס |
|---|---|---|
| מנוע פענוח XML של המסלקה | `services/parser/` | ✅ 106 בדיקות, 88% כיסוי |
| שירות HTTP של המנוע | `services/parser/…/server.py` | ✅ `POST /internal/parse` |
| קורפוס קבצים תקינים ופגומים | `services/parser/tests/fixtures/` | ✅ 16 קבצים מהמחולל |
| Mapping Registry מונחה-דאטה | `services/parser/mappings/` | ✅ YAML; בייצור — טבלת DB |
| סכמת PostgreSQL + RLS | `db/migrations/` | ✅ מאומתת מול PostgreSQL 16 |
| בדיקת בידוד Tenant | `db/tests/rls_test.sql` | ✅ 8 בדיקות |
| **API (NestJS)** | `apps/api/` | ✅ לקוחות, קליטה, תיק 360° |
| **בדיקות אינטגרציה** | `apps/api/test/` | ✅ 10 בדיקות |
| **Frontend (Next.js, RTL)** | `apps/web/` | ✅ רשימת לקוחות + תיק 360° |
| CI | `../.github/workflows/pensionos.yml` | ✅ 3 jobs |

**עדיין לא נבנה:** אינטגרציה למסלקה (E3), מנוע החוקים (E6), מחולל ההנמקה (E7),
e-Sign (E8), Cognito. ראה "הצעד הבא".

---

## הרצה מקומית

### הכל בפקודה אחת

```bash
./scripts/dev-up.sh      # DB → פענוח → API → Frontend
./scripts/demo.sh        # הזרימה המלאה מקצה לקצה בטרמינל
```

| שירות | כתובת |
|---|---|
| Frontend | http://localhost:3000 |
| API | http://localhost:8080 |
| מנוע הפענוח | http://localhost:8081/internal/docs |

### מנוע הפענוח

```bash
cd services/parser
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

python tools/make_fixtures.py     # יצירת קורפוס הבדיקות
pytest                            # 106 בדיקות
pytest --cov=pensionos_parser     # עם כיסוי
```

בדיקת קובץ בודד, עם פלט קריא בעברית:

```bash
python -m pensionos_parser tests/fixtures/01_clean_menora.xml
```

```
========================================================================
קובץ: 01_clean_menora.xml
סטטוס: פוענח במלואו  |  מיפוי: 2026.03  |  תקן: 2.9  |  20ms
לקוח: דנה כהן · ת.ז 039472519
------------------------------------------------------------------------
· pension_comprehensive · מנורה מבטחים · 5512340
    צבירה: ₪842,101 | ד"נ הפקדה: 1.49% | ד"נ צבירה: 0.22% | שלמות: 84%
      כיסוי disability: ₪9,400
· managers_insurance · מנורה מבטחים · 8871200 🔒 מקדם קצבה מובטח
    צבירה: ₪310,500 | ד"נ הפקדה: 4% | ד"נ צבירה: 1.05% | שלמות: 100%
```

`--json` מחזיר את חוזה הפלט המלא (`ParseResult`), כולל `provenance` לכל שדה.
קוד היציאה הוא 1 אם קובץ כלשהו לא נקלט — שימושי ל-CI.

### מסד הנתונים

```bash
createdb pensionos
cd db
for f in migrations/*.sql; do psql -d pensionos -v ON_ERROR_STOP=1 -f "$f"; done
psql -d pensionos -v ON_ERROR_STOP=1 -f dev/local-setup.sql
psql -d pensionos -v ON_ERROR_STOP=1 -f tests/rls_test.sql
```

### API ובדיקות אינטגרציה

```bash
cd apps/api && npm ci && cp .env.example .env
npm run dev                       # :8080
npx tsx --test test/api.test.ts   # דורש DB + parser + API רצים
```

### Frontend

```bash
cd apps/web && npm ci && npm run dev   # :3000
```

---

## החלטות עיצוב שכדאי להכיר לפני שנוגעים בקוד

**1. שדה חסר הוא `null`, לעולם לא `0`.**
המערכות הקיימות מציגות דמי ניהול 0% כשהיצרן לא דיווח — ומטעות את הסוכן.
כאן `0` בדמי ניהול מתורגם ל-`null` + חריג (`allow_zero: false` במיפוי).

**2. המיפוי הוא נתונים, לא קוד.**
תמיכה ביצרן שסוטה מהתקן = רשומת override ב-YAML/DB. אין `if provider == "X"`
בשום מקום. ראה `mappings/standard-2.9.yaml` בסוף הקובץ לדוגמה.

**3. `provenance` לכל שדה — דרישת ציות.**
לכל ערך נשמרים ה-XPath ששימש, הערך הגולמי, רמת הביטחון והתיקונים שבוצעו.
בביקורת צריך להראות מאיזה תג הגיע כל מספר בטבלת ההשוואה שבמסמך ההנמקה.

**4. הצנרת לעולם לא זורקת חריגה.**
כל כשל הופך לסטטוס + רשימת חריגים בעברית. קובץ שנכשל לא נזרק — הוא עובר
להסגר, כדי שלא נצטרך לשלם שוב על אותה בקשה למסלקה.

**5. תיקון "אוטומטי" חשוד מסומן, לא מוסתר.**
יצרן שמדווח `0.0035` במקום `0.35%` — הערך מומר, אבל מקבל
`confidence: 0.75` וחריג `AMBIGUOUS_PERCENT`. היוריסטיקה לא מתחזה לוודאות.

**6. RLS היא רשת הביטחון, לא ההגנה היחידה.**
בדיקות `db/tests/rls_test.sql` רצות בתפקיד ללא `BYPASSRLS` — בדיקה שרצה
כ-superuser תעבור גם כשההגנה שבורה לגמרי. ה-API מסרב לעלות אם הוא מחובר
כ-superuser: שרת מוגדר לא נכון עדיף שלא יעלה מאשר שיעבוד בלי בידוד.

**7. `withTenant` היא הדרך היחידה לגעת בנתוני לקוח.**
היא פותחת טרנזקציה, מזריקה את הקשר ה-RLS מתוך ה-JWT, ורק אז מריצה את
הקוד. אין ב-API אף שאילתה על נתוני לקוח מחוץ לה.

**8. דיווח חדש לא דורס דיווח טוב יותר.**
כלל ה-Reconcile חל גם **בין קבצים**: תאריך נכונות עדכני מנצח, ובתיקו —
הרשומה השלמה יותר. הדילוג מדווח למשתמש (`staleSkipped`) ולא נעשה בשקט.

**9. מרווחים לוגיים ב-RTL — היזהרו מ-`direction` מקומי.**
`ms-*`/`me-*` נפתרים לפי כיוון **האלמנט עצמו**. אלמנט עם `direction: ltr`
(כמו `.num`) יקבל את המרווח בצד ההפוך. המרווח תמיד על העוטף, לא על הרצף
המבודד. מספרים ומזהים בתוך טקסט עברי נעטפים ב-`<bdi>`.

---

## מה נבדק, ומה עוד לא

**נבדק ועובד:**
- 106 בדיקות על מנוע הפענוח (XXE, Billion Laughs, ZIP-bomb, קידודים, אי-התאמת ת"ז)
- 8 בדיקות בידוד Tenant מול PostgreSQL 16, בתפקיד ללא `BYPASSRLS`
- 10 בדיקות אינטגרציה דרך ה-HTTP: אימות, בידוד בין סוכנויות (404 ולא 403),
  אי-דריסת דיווח טוב, הסגר על קובץ של לקוח אחר, ואי-הצגת חוסר כאפס
- `tsc --noEmit` נקי ב-API וב-Frontend; בניית Next.js עוברת

**לא נבדק כי טרם נבנה:** אינטגרציה למסלקה, מנוע החוקים, מחולל ההנמקה, e-Sign.

**⚠️ אימות מול Cognito טרם מומש.** `AUTH_MODE=dev` מנפיק טוקן HS256 מקומי;
המערכת מסרבת לעלות עם `AUTH_MODE=oidc` (זריקה מפורשת ב-`auth.guard.ts`)
ועם `AUTH_MODE=dev` כש-`NODE_ENV=production`.

**⚠️ מגבלה מהותית שיש להכיר:** שמות תגי ה-XML ב-`mappings/standard-2.9.yaml`
הם **ייצוגיים**, ונגזרו מהמבנה המקובל ולא מה-XSD הרשמי. הקורפוס נבנה לפי
אותם שמות, ולכן הבדיקות מאמתות את **מנגנון** הפענוח — לא את נכונות המיפוי
מול התקן. עם קבלת ה-XSD הרשמי (משימה חוסמת ב-Sprint 0) יש להחליף את
ה-XPaths ולהריץ מחדש מול קבצים אמיתיים מאונמזים. המנגנון תוכנן בדיוק כדי
שההחלפה תהיה עדכון נתונים ולא כתיבה מחדש.

**⚠️ ערכים רגולטוריים:** כל רשומה ב-`reco.regulatory_params` המסומנת
`PENDING_VERIFICATION` היא נקודת פתיחה לפיתוח בלבד. המיגרציה מדפיסה אזהרה
כל עוד נותרו רשומות כאלה.

---

## הצעד הבא

לפי סדר התלות:

1. **Clearing Client + Saga (E3)** — מול Mock Server, עם `Idempotency-Key`
   ו-Step Functions. מחליף את ההעלאה הידנית ומייתר את `source='manual_upload'`
   כמסלול העיקרי.
2. **Rules Engine (E6)** — `rule_catalog` כבר בסכמה עם 9 חוקים; חסרים תנאי
   ה-JSONLogic ומנגנון ה-Snapshot הנעול. ה-`advisories` שבתיק 360° הם
   תצוגה בלבד ואינם תחליף.
3. **Cognito** — החלפת `dev-login`. נקודת ההחלפה מוגדרת ב-`auth.guard.ts`
   וב-`lib/api.ts#getToken`; שאר הקוד לא משתנה.
4. **מחולל ההנמקה (E7)** — Compliance Linter + PDF/A.
