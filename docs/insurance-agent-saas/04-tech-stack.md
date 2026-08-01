# 04 — מפרט טכנולוגיות (Tech Stack)

## 1. החלטת ענן: AWS, אזור `il-central-1` (תל אביב)

| שיקול | AWS `il-central-1` | GCP `me-west1` | Azure `Israel Central` |
|---|---|---|---|
| אזור בישראל | ✅ | ✅ | ✅ |
| בשלות שירותי Serverless מנוהלים | ✅ הרחב ביותר | ✅ | ✅ |
| S3 Object Lock (WORM) — קריטי למסמכים חתומים | ✅ בוגר | ⚠️ Bucket Lock, פחות גמיש | ✅ Immutable Blob |
| היכרות בשוק הישראלי / זמינות אנשי DevOps | ✅ הגבוה ביותר | בינוני | בינוני |
| Aurora Serverless v2 | ✅ | ⚠️ AlloyDB — פחות בוגר באזור | ⚠️ |

**החלטה: AWS, `il-central-1`.** מכריע: בשלות S3 Object Lock + KMS + זמינות כוח אדם בישראל.

> ⚠️ **משימת Sprint 0 חוסמת:** לאמת זמינות בפועל של כל שירות ברשימה ב-`il-central-1`
> (חלק מהשירותים מגיעים לאזורים חדשים באיחור). לכל שירות שאינו זמין — לבחור חלופה
> **בתוך האזור**. הכלל הבלתי-עביר: **PII לא יוצא מגבולות ישראל**, גם לא ל-`eu-central-1`.
> שירותים לא-רגישים (CI, ניטור אגרגטיבי ללא PII) יכולים לשבת מחוץ לאזור.

---

## 2. טבלת ה-Stack המלאה

### 2.1 Frontend

| רכיב | בחירה | נימוק |
|---|---|---|
| Framework | **Next.js 15 (App Router) + React 19** | SSR/RSC מוריד JS בצד לקוח, ניתוב קבצים, בשלות אקוסיסטם |
| שפה | **TypeScript 5.x** (`strict: true`) | חובה — הדומיין מלא בטיפוסים רגישים |
| עיצוב | **Tailwind CSS + shadcn/ui (Radix)** | Radix נגיש מהיסוד, RTL נתמך; shadcn = בעלות על הקוד, אין lock-in |
| RTL | `dir="rtl"` + Logical Properties בלבד | ESLint rule חוסם `ml-`/`mr-`/`left`/`right` |
| Server state | **TanStack Query v5** | Cache, retry, optimistic updates |
| Client state | **Zustand** | קליל; אין Redux |
| טפסים | **React Hook Form + Zod** | סכמות משותפות עם ה-BE |
| טבלאות | **TanStack Table** | Headless — שליטה מלאה ב-RTL |
| גרפים | **Recharts** | פשוט, RTL בשליטה, מספיק ל-MVP |
| PDF viewer | **pdf.js** (`react-pdf`) | הצגה בפורטל החתימה ללא הורדה |
| חתימה | **`signature_pad`** על Canvas | קל, נתמך במובייל |
| i18n | **next-intl** — עברית ברירת מחדל, EN Ready | אנגלית לא ב-MVP אבל המבנה כן |
| בדיקות | **Vitest + Testing Library + Playwright** | Playwright גם לרינדור PDF (שימוש כפול) |

### 2.2 Backend

| רכיב | בחירה | נימוק |
|---|---|---|
| API | **NestJS 11 (Node 22 LTS, TypeScript)** | מודולריות מובנית, DI, Guards/Interceptors — מתאים בול ל-Modular Monolith ול-RLS context |
| ORM | **Drizzle ORM** | SQL-first, טיפוסים מלאים, מיגרציות שקופות. **לא Prisma** — היחס שלו ל-RLS ול-`SET LOCAL` בעייתי |
| ולידציה | **Zod** + `nestjs-zod` | חוזה יחיד FE/BE |
| **מנוע פענוח** | **Python 3.12 + lxml + charset-normalizer + Pydantic v2** | ⬅ ראה §3 — החלטה מכוונת |
| Rules Engine | **TypeScript + `json-logic-js`** + חוקים ב-DB | חוקים כ-Data, ניתנים לעדכון ללא Deploy; גרסאות |
| PDF | **Playwright/Chromium + Handlebars → PDF/A-2b** (`ghostscript`/`veraPDF` לוולידציה) | תמיכת RTL/עברית הטובה ביותר; אותו HTML גם לתצוגה מקדימה |
| חתימה דיגיטלית | **PAdES-B-LT** — `pdf-lib` + `node-signpdf` מול **AWS KMS (asymmetric RSA-2048/ECDSA)** + TSA חיצוני (RFC-3161) | מפתח החתימה **לעולם לא יוצא מ-KMS**; אין קובץ `.p12` בשרת |
| Auth | **Amazon Cognito** — OIDC, MFA חובה (TOTP/SMS) | מנוהל, בתוך האזור, זול |
| Authorization | RBAC ב-Guards + **PostgreSQL RLS** | הגנה בשתי שכבות; RLS הוא רשת הביטחון |
| תורים | **SQS (Standard + FIFO ל-clearing)** + DLQ | פשוט, זול, מנוהל |
| Workflow | **AWS Step Functions** ל-Saga של המסלקה | polling ארוך-טווח נכון יותר מ-cron ידני |
| Events | **EventBridge** | Audit + הרחבות עתידיות בלי צימוד |
| Cache/Locks | **ElastiCache Redis (Valkey)** | Idempotency keys, rate limiting, OTP throttling |
| Scheduling | **EventBridge Scheduler** | תזכורות חתימה, ייבוא Benchmarks חודשי |

### 2.3 Data & Storage

| רכיב | בחירה | נימוק |
|---|---|---|
| DB ראשי | **Aurora PostgreSQL Serverless v2 (16.x)** | סקיילינג אוטומטי, RLS, JSONB, Partitioning, `pgcrypto`, PITR 35 יום |
| Extensions | `pgcrypto`, `citext`, `pg_stat_statements`, `pg_trgm`, `uuid-ossp` | חיפוש עברית מטושטש, הצפנת עמודות |
| קבצים גולמיים | **S3** — `raw-clearing/`, SSE-KMS CMK ל-Tenant, Object Lock (Governance) | |
| מסמכים חתומים | **S3** — Object Lock **Compliance Mode, 7 שנים**, Versioning | הדרישה הרגולטורית החזקה ביותר |
| ארכיון | **S3 Glacier Instant Retrieval** דרך Lifecycle | עלות |
| סודות | **Secrets Manager** + רוטציה; **KMS CMK** נפרד ל-Tenant | |
| Search | ❌ אין OpenSearch ב-MVP — `pg_trgm` + GIN | חיסכון בעלות ובתפעול |
| Analytics | ❌ אין Warehouse ב-MVP; ייצוא Parquet ל-S3 מוכן | |

### 2.4 Compute & Infra

| רכיב | בחירה | נימוק |
|---|---|---|
| API runtime | **ECS Fargate** (2–10 tasks, autoscaling) | מריצים Chromium ותהליכים ארוכים; Lambda מגבילה |
| Workers | **Fargate** לקבצים גדולים (עד 4 vCPU/8GB) + **Lambda** למשימות קצרות | קבצי מסלקה 200MB ⇒ Fargate |
| מיכליות | **Docker, multi-stage, distroless/alpine** | |
| IaC | **AWS CDK (TypeScript)** | אותה שפה כמו הצוות; type-safe |
| CI/CD | **GitHub Actions** → OIDC ל-AWS (ללא מפתחות סטטיים) | |
| סביבות | `dev` → `staging` (נתונים סינתטיים בלבד) → `prod` | **אסור להעתיק Production ל-Staging** |
| Monorepo | **pnpm workspaces + Turborepo** | שיתוף `@pensionos/contracts` |

### 2.5 Observability & Security Tooling

| תחום | כלי |
|---|---|
| Logs/Metrics/Traces | **OpenTelemetry** → CloudWatch + X-Ray (או Grafana Cloud ללא PII) |
| Error tracking | **Sentry** (self-hosted או EU) — **חובה: scrubbing מלא של PII לפני שליחה** |
| ניטור עסקי | דשבורד: אחוז פענוח מוצלח, זמן קליטה, Completion rate חתימות |
| התרעות | CloudWatch Alarms → PagerDuty/Slack; P1: אי-התאמת ת"ז, כשל חתימה, DLQ > 0 |
| SAST/SCA | GitHub CodeQL + `npm audit`/`pip-audit` + **Trivy** לתמונות |
| Secrets scanning | Gitleaks ב-pre-commit ו-CI |
| DAST / Pentest | ZAP ב-CI + **מבדק חדירות חיצוני לפני Go-Live** (דרישת תקנות) |

### 2.6 ספקים חיצוניים

| שירות | ספק מומלץ | הערות |
|---|---|---|
| SMS | ספק ישראלי (InforU / Cellact / Twilio) מאחורי `INotificationProvider` | תוכן: קישור + שם פרטי בלבד. **אין PII בהודעה** |
| WhatsApp | WhatsApp Business API דרך BSP (360dialog / Twilio) | תבניות מאושרות מראש; Opt-in נדרש |
| TSA | רשות חותמת זמן RFC-3161 מוכרת | דרישה לתוקף ראייתי לאורך זמן |
| Benchmarks | גמל-נט / פנסיה-נט / data.gov.il | Batch חודשי, ללא PII |

---

## 3. החלטה: למה Python למנוע הפענוח ולא TypeScript?

מדובר בחריגה מודעת מעקרון "שפה אחת". הנימוקים:

1. **`lxml` הוא הכלי הטוב בעולם ל-XML פגום.** `iterparse` יעיל בזיכרון, `recover=True`
   מציל קבצים קטועים, תמיכת XPath 1.0 מלאה. אין מקבילה בשלה ב-Node.
2. **`charset-normalizer`/`chardet`** — זיהוי קידוד עברי (cp1255) ברמה שאין ב-Node.
3. **בידוד blast radius:** הפענוח מעבד קלט לא-מהימן מגורם חיצוני. הרצה בקונטיינר נפרד,
   IAM מינימלי, ללא גישת DB ישירה לכתיבה מחוץ ל-staging schema.
4. **QA של מיפויים:** אנליסט דומיין יכול לכתוב בדיקות מיפוי ב-pytest + pandas בלי להיות מפתח Node.

**המחיר:** צוות דו-לשוני. **ההקלה:** הגבול צר ומוגדר היטב — ה-Parser חושף
`POST /parse` יחיד עם חוזה JSON Schema משותף, ולא נוגע בשום לוגיקה עסקית.
כל מה שמעבר לפענוח — TypeScript.

---

## 4. חוזה השירות של מנוע הפענוח

```jsonc
// POST /internal/parse  (mTLS בלבד, בתוך ה-VPC)
{
  "file_id": "uuid",
  "s3_uri": "s3://pensionos-raw-il/tenant=…/req=…/file.xml",
  "expected_national_id_hash": "base64…",   // אימות שיוך — הגנה מפני דליפה
  "mapping_version": "2026.03",
  "parser_options": { "strict": false, "max_bytes": 209715200 }
}
```

```jsonc
// 200 OK
{
  "status": "partial",                       // succeeded | partial | failed | quarantined
  "parser_version": "1.4.2",
  "sanitize_report": { "fixes": ["reencoded_from_cp1255", "bidi_marks:14"] },
  "entities": {
    "products": [ { "canonical": { /* … */ }, "raw": { /* … */ },
                    "field_provenance": { "management_fee_on_balance_pct":
                      { "xpath": ".//…", "raw": "1,05", "confidence": 0.98 } } } ],
    "policies": [], "coverages": [], "beneficiaries": []
  },
  "issues": [
    { "severity": "warning", "code": "MISSING_FIELD",
      "canonical_field": "fee_agreement_end", "message_he": "מועד סיום הטבת דמי ניהול לא דווח" }
  ],
  "stats": { "accounts": 4, "duration_ms": 812 }
}
```

**`field_provenance` הוא לא נחמד-שיהיה — הוא דרישת ציות.** בביקורת חייבים להראות
מאיזה תג ב-XML הגיע כל מספר בטבלת ההשוואה.

---

## 5. סביבות ואומדן עלות

| סביבה | תצורה | עלות חודשית משוערת (USD) |
|---|---|---|
| `dev` | Aurora Serverless v2 (0.5 ACU min), Fargate 1 task, ללא Multi-AZ | ~$180 |
| `staging` | דומה ל-prod בקטן, נתונים סינתטיים | ~$400 |
| `prod` (פיילוט: 3 סוכנויות, ~40 סוכנים, ~8,000 לקוחות) | Aurora 2–8 ACU Multi-AZ, 2–6 Fargate, S3 ~500GB, WAF, CloudFront | **~$1,400–1,900** |

**עלויות שאינן ענן:** בקשות מסלקה (לפי תעריף, חיוב לפי `cost_agorot` — נמדד ומוצג),
SMS/WhatsApp (~₪0.05–0.12 להודעה), TSA (מנוי), Pentest חיצוני (חד-פעמי, ~$8–15K).

---

## 6. NFRs — דרישות לא-פונקציונליות

| קטגוריה | דרישה |
|---|---|
| זמינות | 99.5% בשעות עבודה (07:00–21:00 IL); Multi-AZ; RTO 4h, RPO 15m |
| ביצועים | P95 טעינת תיק 360° < 1.2s; הפקת PDF < 8s; פענוח קובץ ממוצע < 15s |
| סקלביליות | 10K לקוחות/Tenant, 200 בקשות מסלקה מקבילות ללא degradation |
| גיבוי | Aurora PITR 35 יום + snapshot יומי מוצפן; **תרגיל שחזור רבעוני מתועד** |
| נגישות | ת"י 5568 / WCAG 2.1 AA — חובה בפורטל החתימה |
| דפדפנים | Chrome/Edge/Safari/Firefox 2 גרסאות אחרונות; פורטל חתימה: iOS 14+/Android 9+ |
| שפה | עברית מלאה RTL; מבנה מוכן ל-i18n |
| API | REST + OpenAPI 3.1 אוטומטי; גרסאות `/v1`; `Idempotency-Key` בכל POST כספי/חיצוני |
