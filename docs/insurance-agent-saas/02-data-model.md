# 02 — מודל נתונים ו-ERD

## 1. עקרונות מודל הנתונים

1. **PostgreSQL כמקור אמת יחיד** לנתונים הקנוניים. אין Polyglot persistence ב-MVP.
2. **Raw ב-S3, Canonical ב-PG, Semi-structured ב-JSONB.** ה-XML הגולמי לעולם לא נכנס לטבלה.
3. **כל טבלה עסקית נושאת `tenant_id`** ומוגנת ב-RLS. אין יוצא מן הכלל.
4. **Snapshots הם Immutable.** נתוני התיק כפי שהיו בזמן ההמלצה נשמרים כ-JSONB חתום,
   בנפרד מהטבלאות החיות. זה מה שמאפשר לענות בביקורת: "על סמך מה המלצת?"
5. **Soft delete בלבד** לישויות עסקיות (`deleted_at`), כדי לא לשבור שרשרת אודיט.
   מחיקה פיזית מתבצעת רק ע"י תהליך Retention ייעודי (§6).
6. **Schema per module** — הכנה לפיצול עתידי לשירותים.

---

## 2. ERD ראשי

```mermaid
erDiagram
    TENANTS ||--o{ USERS : "מעסיקה"
    TENANTS ||--o{ CLIENTS : "מנהלת"
    USERS ||--o{ CLIENTS : "מטפל ב-"
    CLIENTS ||--o{ CLIENT_FAMILY_MEMBERS : "בני משפחה"
    CLIENTS ||--o{ CLIENT_CONSENTS : "ייפויי כוח"
    CLIENTS ||--o{ CLEARING_REQUESTS : "בקשות מסלקה"
    CLEARING_REQUESTS ||--o{ CLEARING_FILES : "קבצים"
    CLEARING_FILES ||--o{ PARSE_JOBS : "עבודות פענוח"
    PARSE_JOBS ||--o{ PARSE_ISSUES : "חריגים"
    PROVIDERS ||--o{ CLEARING_FILES : "יצרן מדווח"

    CLIENTS ||--o{ PRODUCTS : "נכסים פנסיוניים"
    PROVIDERS ||--o{ PRODUCTS : "מנוהל ע\"י"
    PRODUCTS ||--o{ PRODUCT_BALANCES : "יתרות"
    PRODUCTS ||--o{ PRODUCT_FEES : "דמי ניהול"
    PRODUCTS ||--o{ INVESTMENT_TRACKS : "מסלולי השקעה"
    PRODUCTS ||--o{ COVERAGES : "כיסויים"
    PRODUCTS ||--o{ BENEFICIARIES : "מוטבים"
    PRODUCTS ||--o{ DEPOSITS : "הפקדות"

    CLIENTS ||--o{ POLICIES : "פוליסות פרט"
    POLICIES ||--o{ COVERAGES : "כיסויים"
    PROVIDERS ||--o{ POLICIES : "מבטח"

    CLIENTS ||--o{ PORTFOLIO_SNAPSHOTS : "צילומי תיק"
    PORTFOLIO_SNAPSHOTS ||--o{ RECOMMENDATIONS : "בסיס להמלצה"
    RECOMMENDATIONS ||--o{ RECOMMENDATION_MOVES : "מהלכים"
    RECOMMENDATIONS ||--o{ RECOMMENDATION_FLAGS : "אזהרות"
    RECOMMENDATIONS ||--o{ COMPARISON_LINES : "שורות השוואה"
    RECOMMENDATIONS ||--|| DOCUMENTS : "מסמך הנמקה"

    DOCUMENTS ||--o{ DOCUMENT_VERSIONS : "גרסאות"
    DOCUMENT_VERSIONS ||--o{ SIGNATURE_ENVELOPES : "מעטפות חתימה"
    SIGNATURE_ENVELOPES ||--o{ SIGNERS : "חותמים"
    SIGNATURE_ENVELOPES ||--o{ SIGNATURE_EVENTS : "ראיות"
    SIGNATURE_ENVELOPES ||--o{ NOTIFICATIONS : "שליחות"

    CLIENTS ||--o{ INTERACTIONS : "אינטראקציות"
    USERS ||--o{ INTERACTIONS : "בוצע ע\"י"
    TENANTS ||--o{ AUDIT_LOGS : "יומן ביקורת"
    REGULATORY_PARAMS ||--o{ RECOMMENDATIONS : "פרמטרים בתוקף"
    BENCHMARKS ||--o{ COMPARISON_LINES : "מדדי השוואה"
```

---

## 3. פירוט הטבלאות המרכזיות

### 3.1 Identity & Tenancy

```sql
CREATE SCHEMA identity;

CREATE TABLE identity.tenants (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  legal_name       TEXT NOT NULL,
  license_number   TEXT NOT NULL,              -- מספר רישיון סוכנות
  tax_id           TEXT NOT NULL,              -- ח.פ
  kms_key_arn      TEXT NOT NULL,              -- CMK ייעודי ל-tenant
  data_region      TEXT NOT NULL DEFAULT 'il-central-1',
  status           TEXT NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active','suspended','offboarding')),
  retention_policy JSONB NOT NULL DEFAULT '{"documents_years":7,"raw_files_years":7}',
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE identity.users (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      UUID NOT NULL REFERENCES identity.tenants(id),
  cognito_sub    TEXT NOT NULL UNIQUE,
  full_name      TEXT NOT NULL,
  email          CITEXT NOT NULL,
  phone_e164     TEXT,
  license_number TEXT,                          -- רישיון בעל הרישיון (סוכן)
  license_types  TEXT[] NOT NULL DEFAULT '{}',  -- pension | life | health | elementary
  role           TEXT NOT NULL
                 CHECK (role IN ('agent','agency_admin','compliance','support')),
  mfa_enabled    BOOLEAN NOT NULL DEFAULT false,
  last_login_at  TIMESTAMPTZ,
  deleted_at     TIMESTAMPTZ,
  UNIQUE (tenant_id, email)
);
```

### 3.2 Clients — תיק לקוח

```sql
CREATE SCHEMA clients;

CREATE TABLE clients.clients (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          UUID NOT NULL REFERENCES identity.tenants(id),
  owner_user_id      UUID REFERENCES identity.users(id),

  -- ת"ז מוצפנת ברמת עמודה + hash לחיפוש (אף פעם לא מחפשים על הערך הגלוי)
  national_id_enc    BYTEA NOT NULL,
  national_id_hash   BYTEA NOT NULL,            -- HMAC-SHA256 עם מפתח per-tenant
  national_id_last4  TEXT NOT NULL,             -- לאימות בחתימה בלבד

  first_name         TEXT NOT NULL,
  last_name          TEXT NOT NULL,
  birth_date         DATE,
  gender             TEXT CHECK (gender IN ('m','f','other','unspecified')),
  marital_status     TEXT,
  phone_e164         TEXT,
  email              CITEXT,
  address            JSONB,

  employment         JSONB,   -- {status, employer_name, employer_tax_id, gross_salary, seniority_date}
  financial_profile  JSONB,   -- {risk_appetite, retirement_age_target, monthly_expenses}
  health_declaration JSONB,   -- מידע רגיש: מצב רפואי מוצהר, מעשן — נדרש לחוקי הסיכון

  status             TEXT NOT NULL DEFAULT 'active',
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at         TIMESTAMPTZ,
  UNIQUE (tenant_id, national_id_hash)
);
CREATE INDEX ON clients.clients (tenant_id, last_name, first_name)
  WHERE deleted_at IS NULL;

CREATE TABLE clients.family_members (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL,
  client_id     UUID NOT NULL REFERENCES clients.clients(id) ON DELETE CASCADE,
  relation      TEXT NOT NULL CHECK (relation IN
                ('spouse','child','parent','sibling','common_law_partner','other')),
  first_name    TEXT NOT NULL,
  last_name     TEXT,
  national_id_enc BYTEA,
  birth_date    DATE,
  is_dependent  BOOLEAN NOT NULL DEFAULT false,   -- משפיע על חישוב שאירים
  is_insured    BOOLEAN NOT NULL DEFAULT false,   -- מבוטח בפוליסות פרט
  notes         TEXT
);

-- ייפוי כוח / הרשאת פנייה למסלקה
CREATE TABLE clients.consents (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL,
  client_id       UUID NOT NULL REFERENCES clients.clients(id),
  consent_type    TEXT NOT NULL CHECK (consent_type IN
                  ('clearing_poa','data_processing','marketing','har_habituach')),
  scope           JSONB NOT NULL,        -- {products:[...], full_info:true}
  granted_at      TIMESTAMPTZ NOT NULL,
  expires_at      TIMESTAMPTZ,
  revoked_at      TIMESTAMPTZ,
  evidence_s3_key TEXT,                  -- מסמך/הקלטה/חתימה
  evidence_sha256 BYTEA,
  created_by      UUID REFERENCES identity.users(id)
);
CREATE INDEX ON clients.consents (client_id, consent_type)
  WHERE revoked_at IS NULL;
```

### 3.3 Clearing — קליטה מהמסלקה

```sql
CREATE SCHEMA clearing;

CREATE TABLE clearing.providers (               -- טבלת ייחוס גלובלית (ללא tenant)
  code            TEXT PRIMARY KEY,             -- קוד יצרן לפי הרשות
  name_he         TEXT NOT NULL,
  provider_type   TEXT NOT NULL,                -- insurer | pension_fund | provident | investment_house
  standard_quirks JSONB NOT NULL DEFAULT '{}'   -- חריגות ידועות בדיווח
);

CREATE TABLE clearing.requests (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          UUID NOT NULL,
  client_id          UUID NOT NULL REFERENCES clients.clients(id),
  requested_by       UUID NOT NULL REFERENCES identity.users(id),
  consent_id         UUID NOT NULL REFERENCES clients.consents(id),

  request_type       TEXT NOT NULL CHECK (request_type IN ('full','partial','specific_provider')),
  external_ref       TEXT,                      -- מזהה הבקשה במסלקה
  status             TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                     ('draft','submitted','in_progress','partial','completed','failed','expired')),
  submitted_at       TIMESTAMPTZ,
  completed_at       TIMESTAMPTZ,
  next_poll_at       TIMESTAMPTZ,
  poll_attempts      INT NOT NULL DEFAULT 0,
  cost_agorot        INT,                       -- עלות הבקשה — לחיוב/בקרה
  error              JSONB,
  idempotency_key    TEXT NOT NULL,
  UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE clearing.files (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL,
  request_id      UUID NOT NULL REFERENCES clearing.requests(id),
  provider_code   TEXT REFERENCES clearing.providers(code),
  s3_bucket       TEXT NOT NULL,
  s3_key          TEXT NOT NULL,
  original_name   TEXT,
  size_bytes      BIGINT,
  sha256          BYTEA NOT NULL,
  declared_encoding TEXT,
  detected_encoding TEXT,
  standard_version  TEXT,
  status          TEXT NOT NULL DEFAULT 'landed' CHECK (status IN
                  ('landed','sanitized','parsed','no_data','quarantined','failed')),
  received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, sha256)                    -- דדופליקציה טבעית
);

CREATE TABLE clearing.parse_jobs (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      UUID NOT NULL,
  file_id        UUID NOT NULL REFERENCES clearing.files(id),
  status         TEXT NOT NULL DEFAULT 'queued' CHECK (status IN
                 ('queued','running','succeeded','partial','failed','quarantined')),
  parser_version TEXT NOT NULL,
  mapping_version TEXT NOT NULL,
  sanitize_report JSONB,                        -- אילו תיקוני קידוד בוצעו
  stats          JSONB,                         -- {accounts:12, coverages:31, skipped:2}
  started_at     TIMESTAMPTZ,
  finished_at    TIMESTAMPTZ,
  duration_ms    INT
);

CREATE TABLE clearing.parse_issues (
  id            BIGSERIAL PRIMARY KEY,
  tenant_id     UUID NOT NULL,
  parse_job_id  UUID NOT NULL REFERENCES clearing.parse_jobs(id),
  severity      TEXT NOT NULL CHECK (severity IN ('info','warning','error','blocker')),
  code          TEXT NOT NULL,                  -- MISSING_FIELD | BAD_ENCODING | OUT_OF_RANGE ...
  canonical_field TEXT,
  xpath         TEXT,
  raw_value     TEXT,
  message_he    TEXT NOT NULL,
  resolved_at   TIMESTAMPTZ,
  resolved_by   UUID REFERENCES identity.users(id)
);

-- מיפוי מונחה-דאטה (ראה 01-architecture §3.3)
CREATE TABLE clearing.field_mappings (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_field   TEXT NOT NULL,
  standard_version  TEXT NOT NULL,
  provider_code     TEXT NOT NULL DEFAULT '*',
  xpath             TEXT NOT NULL,
  fallback_xpaths   TEXT[] NOT NULL DEFAULT '{}',
  data_type         TEXT NOT NULL,
  transforms        TEXT[] NOT NULL DEFAULT '{}',
  validation        JSONB,
  on_missing        TEXT NOT NULL DEFAULT 'null',
  required_for      TEXT[] NOT NULL DEFAULT '{}',
  effective_from    DATE NOT NULL,
  effective_to      DATE,
  UNIQUE (canonical_field, standard_version, provider_code, effective_from)
);
```

### 3.4 Portfolio — הנתונים הקנוניים

```sql
CREATE SCHEMA portfolio;

-- מוצרים פנסיוניים/פיננסיים: פנסיה, גמל, השתלמות, ביטוח מנהלים, גמל להשקעה
CREATE TABLE portfolio.products (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          UUID NOT NULL,
  client_id          UUID NOT NULL REFERENCES clients.clients(id),
  provider_code      TEXT NOT NULL REFERENCES clearing.providers(code),
  source_file_id     UUID REFERENCES clearing.files(id),

  product_type       TEXT NOT NULL CHECK (product_type IN (
                     'pension_comprehensive','pension_general','pension_old',
                     'provident_fund','study_fund','managers_insurance',
                     'provident_investment','other','unknown')),
  policy_number      TEXT NOT NULL,
  product_name       TEXT,
  join_date          DATE,
  status             TEXT NOT NULL DEFAULT 'active' CHECK (status IN
                     ('active','paid_up','frozen','closed','unknown')),  -- paid_up = מסולק
  is_dormant         BOOLEAN NOT NULL DEFAULT false,
  employer_name      TEXT,

  -- דגלים קריטיים לחוקי הסיכון
  has_guaranteed_annuity_factor BOOLEAN,      -- מקדם קצבה מובטח
  guaranteed_factor_value       NUMERIC(8,4),
  is_pre_2013                   BOOLEAN,
  medical_underwriting_notes    JSONB,        -- חריגים/החרגות רפואיות

  report_date        DATE NOT NULL,           -- תאריך נכונות הנתונים
  data_completeness  NUMERIC(4,3),            -- 0..1 — כמה שדות חובה התקבלו
  raw                JSONB NOT NULL,          -- ה-extraction המלא, למקרה שנצטרך שדה נוסף
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, client_id, provider_code, policy_number, product_type)
);
CREATE INDEX ON portfolio.products (tenant_id, client_id) WHERE status <> 'closed';

CREATE TABLE portfolio.product_balances (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          UUID NOT NULL,
  product_id         UUID NOT NULL REFERENCES portfolio.products(id) ON DELETE CASCADE,
  as_of_date         DATE NOT NULL,
  total_balance      NUMERIC(14,2),
  employee_component NUMERIC(14,2),
  employer_component NUMERIC(14,2),
  severance_component NUMERIC(14,2),     -- פיצויים
  taxable_split      JSONB,              -- {exempt, taxable}
  ytd_yield_pct      NUMERIC(6,3),
  yield_3y_pct       NUMERIC(6,3),
  UNIQUE (product_id, as_of_date)
);

CREATE TABLE portfolio.product_fees (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id             UUID NOT NULL,
  product_id            UUID NOT NULL REFERENCES portfolio.products(id) ON DELETE CASCADE,
  as_of_date            DATE NOT NULL,
  fee_on_deposit_pct    NUMERIC(6,3),    -- דמי ניהול מהפקדה
  fee_on_balance_pct    NUMERIC(6,3),    -- דמי ניהול מצבירה
  fee_expenses_pct      NUMERIC(6,3),    -- הוצאות ניהול השקעות
  fee_agreement_end     DATE,            -- סיום הטבת דמי ניהול — קריטי להנמקה!
  regulatory_cap_deposit_pct NUMERIC(6,3),
  regulatory_cap_balance_pct NUMERIC(6,3),
  is_promotional        BOOLEAN NOT NULL DEFAULT false,
  UNIQUE (product_id, as_of_date)
);

CREATE TABLE portfolio.investment_tracks (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      UUID NOT NULL,
  product_id     UUID NOT NULL REFERENCES portfolio.products(id) ON DELETE CASCADE,
  track_code     TEXT,
  track_name     TEXT,
  allocation_pct NUMERIC(6,3),
  is_age_based   BOOLEAN,                -- מסלול תלוי גיל (ברירת מחדל)
  risk_level     TEXT
);

-- פוליסות פרט: בריאות, סיעוד, חיים (ריסק), תאונות אישיות, נסיעות
CREATE TABLE portfolio.policies (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL,
  client_id         UUID NOT NULL REFERENCES clients.clients(id),
  provider_code     TEXT NOT NULL REFERENCES clearing.providers(code),
  policy_number     TEXT NOT NULL,
  policy_type       TEXT NOT NULL CHECK (policy_type IN
                    ('health','ltc','life_risk','personal_accident','disability','travel','other')),
  insured_member_id UUID REFERENCES clients.family_members(id),  -- מי המבוטח
  start_date        DATE,
  end_date          DATE,
  status            TEXT NOT NULL DEFAULT 'active',
  monthly_premium   NUMERIC(12,2),
  premium_track     TEXT,                -- קבוע / משתנה לפי גיל
  source            TEXT NOT NULL CHECK (source IN ('clearing','har_habituach','manual')),
  source_ref        TEXT,
  generation_note   TEXT,                -- "דור" הפוליסה — לצורך אזהרת החלפה
  raw               JSONB,
  report_date       DATE NOT NULL,
  UNIQUE (tenant_id, client_id, provider_code, policy_number)
);

-- כיסויים — משותף למוצרים פנסיוניים ולפוליסות פרט
CREATE TABLE portfolio.coverages (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL,
  product_id        UUID REFERENCES portfolio.products(id) ON DELETE CASCADE,
  policy_id         UUID REFERENCES portfolio.policies(id) ON DELETE CASCADE,
  coverage_type     TEXT NOT NULL,       -- disability | survivors | death | surgery | ltc ...
  coverage_name     TEXT,
  sum_insured       NUMERIC(14,2),
  monthly_benefit   NUMERIC(12,2),
  cost_monthly      NUMERIC(12,2),
  waiting_period_m  INT,                 -- תקופת אכשרה
  exclusions        JSONB,               -- החרגות / מצב רפואי קודם
  is_active         BOOLEAN NOT NULL DEFAULT true,
  CHECK (num_nonnulls(product_id, policy_id) = 1)
);

CREATE TABLE portfolio.beneficiaries (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL,
  product_id    UUID REFERENCES portfolio.products(id) ON DELETE CASCADE,
  policy_id     UUID REFERENCES portfolio.policies(id) ON DELETE CASCADE,
  full_name     TEXT,
  relation      TEXT,
  share_pct     NUMERIC(5,2),
  updated_on    DATE
);

CREATE TABLE portfolio.deposits (
  id            BIGSERIAL PRIMARY KEY,
  tenant_id     UUID NOT NULL,
  product_id    UUID NOT NULL REFERENCES portfolio.products(id) ON DELETE CASCADE,
  month         DATE NOT NULL,
  employee_amt  NUMERIC(12,2),
  employer_amt  NUMERIC(12,2),
  severance_amt NUMERIC(12,2),
  salary_base   NUMERIC(12,2)
) PARTITION BY RANGE (month);
```

### 3.5 Snapshots — לב הציות

```sql
CREATE TABLE portfolio.snapshots (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL,
  client_id       UUID NOT NULL REFERENCES clients.clients(id),
  created_by      UUID NOT NULL REFERENCES identity.users(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

  payload         JSONB NOT NULL,      -- העתק מלא ומקובע של התיק בזמן ההמלצה
  payload_sha256  BYTEA NOT NULL,
  source_file_ids UUID[] NOT NULL,     -- אילו קבצי מסלקה הרכיבו אותו
  source_sha256s  BYTEA[] NOT NULL,
  parser_version  TEXT NOT NULL,
  mapping_version TEXT NOT NULL,
  completeness    JSONB NOT NULL,      -- {missing_fields:[...], products_with_gaps:[...]}
  is_locked       BOOLEAN NOT NULL DEFAULT true
);
-- אין UPDATE/DELETE. נאכף ב-Trigger + הרשאות.
CREATE RULE snapshots_no_update AS ON UPDATE TO portfolio.snapshots DO INSTEAD NOTHING;
CREATE RULE snapshots_no_delete AS ON DELETE TO portfolio.snapshots DO INSTEAD NOTHING;
```

### 3.6 Recommendations & Documents

```sql
CREATE SCHEMA reco;

CREATE TABLE reco.recommendations (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL,
  client_id         UUID NOT NULL REFERENCES clients.clients(id),
  snapshot_id       UUID NOT NULL REFERENCES portfolio.snapshots(id),
  agent_id          UUID NOT NULL REFERENCES identity.users(id),

  status            TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                    ('draft','blocked','ready','document_generated','sent','signed','cancelled')),
  client_needs      JSONB NOT NULL,   -- צרכים, מטרות, העדפות שהלקוח מסר
  client_declined_info BOOLEAN NOT NULL DEFAULT false,  -- הלקוח סירב למסור מידע
  declined_info_impact TEXT,                            -- השפעת אי-המסירה (דרישת חובה)
  agent_disclosure  JSONB NOT NULL,   -- זיקה לגופים מוסדיים, אופן התגמול
  rules_version     TEXT NOT NULL,
  reg_params_version TEXT NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE reco.moves (                 -- המהלכים המומלצים
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL,
  recommendation_id UUID NOT NULL REFERENCES reco.recommendations(id) ON DELETE CASCADE,
  move_type         TEXT NOT NULL CHECK (move_type IN
                    ('transfer','new_product','track_change','fee_change',
                     'coverage_add','coverage_change','coverage_cancel','no_change')),
  source_product_id UUID REFERENCES portfolio.products(id),
  source_policy_id  UUID REFERENCES portfolio.policies(id),
  target_provider_code TEXT REFERENCES clearing.providers(code),
  target_spec       JSONB NOT NULL,      -- מוצר/מסלול/דמי ניהול/כיסויים מוצעים
  rationale_codes   TEXT[] NOT NULL,     -- נימוקים מקטלוג מאושר
  rationale_free_text TEXT,              -- נימוק חופשי של הסוכן
  amount_estimate   NUMERIC(14,2),
  sort_order        INT NOT NULL DEFAULT 0
);

CREATE TABLE reco.flags (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL,
  recommendation_id UUID NOT NULL REFERENCES reco.recommendations(id) ON DELETE CASCADE,
  move_id           UUID REFERENCES reco.moves(id) ON DELETE CASCADE,
  rule_id           TEXT NOT NULL,       -- R-PEN-001 ...
  severity          TEXT NOT NULL CHECK (severity IN ('info','warning','critical','blocker')),
  message_he        TEXT NOT NULL,
  requires_ack      BOOLEAN NOT NULL DEFAULT false,
  agent_ack_at      TIMESTAMPTZ,
  agent_ack_text    TEXT,
  client_ack_at     TIMESTAMPTZ          -- אישור נפרד של הלקוח בעת החתימה
);

CREATE TABLE reco.comparison_lines (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL,
  recommendation_id UUID NOT NULL REFERENCES reco.recommendations(id) ON DELETE CASCADE,
  section           TEXT NOT NULL,       -- fees | coverage | yield | track
  label_he          TEXT NOT NULL,
  current_value     JSONB,
  proposed_value    JSONB,
  benchmark_value   JSONB,
  delta             JSONB,
  unit              TEXT,
  sort_order        INT NOT NULL DEFAULT 0
);

CREATE SCHEMA docs;

CREATE TABLE docs.documents (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          UUID NOT NULL,
  client_id          UUID NOT NULL,
  recommendation_id  UUID REFERENCES reco.recommendations(id),
  doc_type           TEXT NOT NULL CHECK (doc_type IN
                     ('reasoning','disclosure','poa','consent','other')),
  title              TEXT NOT NULL,
  current_version_id UUID,
  supersedes_id      UUID REFERENCES docs.documents(id),
  status             TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                     ('draft','generated','sent','signed','void','superseded')),
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE docs.document_versions (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      UUID NOT NULL,
  document_id    UUID NOT NULL REFERENCES docs.documents(id),
  version_no     INT NOT NULL,
  template_id    TEXT NOT NULL,
  template_version TEXT NOT NULL,
  content_model  JSONB NOT NULL,        -- הקלט המדויק לרינדור — שחזור מלא אפשרי
  s3_key         TEXT NOT NULL,
  sha256         BYTEA NOT NULL,
  page_count     INT,
  rendered_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  is_locked      BOOLEAN NOT NULL DEFAULT false,
  UNIQUE (document_id, version_no)
);
```

### 3.7 Signatures

```sql
CREATE SCHEMA sign;

CREATE TABLE sign.envelopes (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           UUID NOT NULL,
  document_version_id UUID NOT NULL REFERENCES docs.document_versions(id),
  created_by          UUID NOT NULL REFERENCES identity.users(id),
  token_hash          BYTEA NOT NULL UNIQUE,     -- שומרים hash, לא את הטוקן
  channel             TEXT NOT NULL CHECK (channel IN ('sms','whatsapp','email','in_person')),
  status              TEXT NOT NULL DEFAULT 'created' CHECK (status IN
                      ('created','sent','delivered','opened','identified','signed',
                       'declined','expired','cancelled')),
  expires_at          TIMESTAMPTZ NOT NULL,
  signed_at           TIMESTAMPTZ,
  signed_s3_key       TEXT,
  signed_sha256       BYTEA,
  tsa_token           BYTEA,                     -- RFC-3161
  evidence            JSONB,                     -- Evidence Package
  reminders_sent      INT NOT NULL DEFAULT 0
);

CREATE TABLE sign.signers (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL,
  envelope_id   UUID NOT NULL REFERENCES sign.envelopes(id) ON DELETE CASCADE,
  role          TEXT NOT NULL CHECK (role IN ('client','agent','spouse','guardian')),
  full_name     TEXT NOT NULL,
  phone_e164    TEXT,
  national_id_last4 TEXT,
  signed_at     TIMESTAMPTZ,
  signature_image_s3_key TEXT,
  signature_image_sha256 BYTEA
);

CREATE TABLE sign.events (               -- Append-only, ראייתי
  id            BIGSERIAL PRIMARY KEY,
  tenant_id     UUID NOT NULL,
  envelope_id   UUID NOT NULL REFERENCES sign.envelopes(id),
  event_type    TEXT NOT NULL,           -- sent | delivered | opened | otp_sent |
                                         -- otp_failed | otp_verified | scrolled_end |
                                         -- signed | declined | expired
  occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  ip_address    INET,
  user_agent    TEXT,
  geo_country   TEXT,
  metadata      JSONB
);
```

### 3.8 Interactions, Audit, Reference Data

```sql
CREATE TABLE clients.interactions (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL,
  client_id     UUID NOT NULL REFERENCES clients.clients(id),
  user_id       UUID REFERENCES identity.users(id),
  type          TEXT NOT NULL CHECK (type IN
                ('meeting','call','whatsapp','email','system_event','note','task')),
  direction     TEXT CHECK (direction IN ('inbound','outbound','internal')),
  subject       TEXT,
  body          TEXT,
  related_entity TEXT,                    -- recommendation | document | clearing_request
  related_id    UUID,
  occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  due_at        TIMESTAMPTZ,              -- למשימות
  completed_at  TIMESTAMPTZ
);
CREATE INDEX ON clients.interactions (tenant_id, client_id, occurred_at DESC);

CREATE SCHEMA audit;
CREATE TABLE audit.logs (
  id            BIGSERIAL PRIMARY KEY,
  tenant_id     UUID NOT NULL,
  actor_user_id UUID,
  actor_type    TEXT NOT NULL DEFAULT 'user',   -- user | system | worker | support
  action        TEXT NOT NULL,                  -- READ | CREATE | UPDATE | EXPORT | SIGN | LOGIN
  entity_type   TEXT NOT NULL,
  entity_id     UUID,
  client_id     UUID,                           -- למי שייך המידע שניגשו אליו
  ip_address    INET,
  user_agent    TEXT,
  request_id    TEXT,
  before        JSONB,
  after         JSONB,
  occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now()
) PARTITION BY RANGE (occurred_at);
-- Append-only: אין הרשאות UPDATE/DELETE לתפקיד האפליקציה.

-- פרמטרים רגולטוריים כ-DATA ולא כקוד
CREATE TABLE reco.regulatory_params (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  param_key      TEXT NOT NULL,        -- max_fee_balance.pension_comprehensive
  param_value    JSONB NOT NULL,
  source_ref     TEXT NOT NULL,        -- הפניה לחוזר/תקנה
  effective_from DATE NOT NULL,
  effective_to   DATE,
  version        TEXT NOT NULL,
  UNIQUE (param_key, effective_from)
);

CREATE TABLE reco.benchmarks (          -- מגמל-נט / פנסיה-נט, טעינה חודשית
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider_code  TEXT NOT NULL,
  product_type   TEXT NOT NULL,
  track_code     TEXT,
  period         DATE NOT NULL,
  yield_pct      NUMERIC(6,3),
  yield_3y_pct   NUMERIC(6,3),
  yield_5y_pct   NUMERIC(6,3),
  avg_fee_deposit_pct NUMERIC(6,3),
  avg_fee_balance_pct NUMERIC(6,3),
  sharpe         NUMERIC(6,3),
  UNIQUE (provider_code, product_type, track_code, period)
);
```

---

## 4. בידוד Tenant — Row Level Security

```sql
ALTER TABLE clients.clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE clients.clients FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON clients.clients
  USING      (tenant_id = current_setting('app.current_tenant', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant', true)::uuid);

-- הגבלה נוספת: סוכן רגיל רואה רק לקוחות שהוא הבעלים שלהם
CREATE POLICY agent_scope ON clients.clients
  FOR SELECT
  USING (
    current_setting('app.current_role', true) IN ('agency_admin','compliance')
    OR owner_user_id = current_setting('app.current_user', true)::uuid
  );
```

ה-Interceptor של NestJS מבצע `SET LOCAL app.current_tenant/current_user/current_role`
בתחילת כל טרנזקציה, מתוך ה-JWT. **Connection pool מוגדר ב-`transaction` mode**
כדי ש-`SET LOCAL` לא ידלוף בין בקשות.

**בדיקת CI חוסמת:** מיגרציה שמוסיפה טבלה עם `tenant_id` בלי RLS Policy — נכשלת ב-CI.

---

## 5. אינדוקס וביצועים

| שאילתה חמה | אינדקס |
|---|---|
| רשימת לקוחות + חיפוש | `(tenant_id, last_name, first_name)`, `GIN` על `to_tsvector('simple', name)` |
| חיפוש לפי ת"ז | `(tenant_id, national_id_hash)` — **לעולם לא על הערך הגלוי** |
| תיק 360° של לקוח | `(tenant_id, client_id)` על products/policies/coverages |
| Polling של בקשות מסלקה | Partial index: `(next_poll_at) WHERE status='in_progress'` |
| מעטפות פתוחות לתזכורת | `(expires_at) WHERE status IN ('sent','opened')` |
| Audit לפי לקוח | Partition חודשי + `(tenant_id, client_id, occurred_at DESC)` |

**חלוקה (Partitioning):** `audit.logs` ו-`portfolio.deposits` לפי חודש, עם ניתוק
פרטישנים ישנים ל-S3 (`aws_s3` export) בתום תקופת השמירה החמה.

---

## 6. מדיניות שמירה ומחיקה (Retention)

| סוג נתון | שמירה חמה | ארכיון | מחיקה |
|---|---|---|---|
| קבצי XML גולמיים | 90 יום ב-S3 Standard | Glacier IR עד 7 שנים | מחיקה אוטומטית + רישום |
| מסמכים חתומים | 7 שנים ב-S3 Object Lock (Compliance) | — | לא ניתן למחוק לפני תום התקופה — גם לא ע"י root |
| Snapshots | 7 שנים | JSONB דחוס | לפי מדיניות Tenant |
| `audit.logs` | 24 חודשים חמים (דרישת תקנות אבטחת מידע) | 7 שנים בארכיון | — |
| נתוני לקוח שנמחק | Soft delete מיידי | הצפנה + נעילה | Crypto-shredding: מחיקת מפתח ההצפנה של הלקוח |
| Offboarding של Tenant | ייצוא מלא (JSON+PDF) תוך 30 יום | — | מחיקת CMK של ה-Tenant ⇒ כל ה-S3 שלו בלתי-קריא |

> **Crypto-shredding** הוא המנגנון שמאפשר לכבד בקשת מחיקה גם על אובייקטים ב-WORM:
> האובייקט נשאר, המפתח נמחק, המידע אבוד מתמטית — בלי לשבור את חובות השמירה על השרשרת.
