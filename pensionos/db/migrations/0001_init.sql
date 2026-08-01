-- =====================================================================
-- PensionOS · Migration 0001 · סכמה ראשונית
--
-- עקרונות (ראה docs/insurance-agent-saas/02-data-model.md):
--   1. tenant_id בכל טבלה עסקית + RLS כפוי. אין יוצא מן הכלל.
--   2. ת"ז מוצפנת ברמת עמודה; חיפוש דרך HMAC בלבד.
--   3. Snapshots ומסמכים חתומים — Immutable ברמת מסד הנתונים.
--   4. Schema per module — הכנה לפיצול עתידי לשירותים.
--   5. Soft delete בלבד; מחיקה פיזית רק דרך תהליך Retention.
-- =====================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE SCHEMA IF NOT EXISTS identity;
CREATE SCHEMA IF NOT EXISTS clients;
CREATE SCHEMA IF NOT EXISTS clearing;
CREATE SCHEMA IF NOT EXISTS portfolio;
CREATE SCHEMA IF NOT EXISTS reco;
CREATE SCHEMA IF NOT EXISTS docs;
CREATE SCHEMA IF NOT EXISTS sign;
CREATE SCHEMA IF NOT EXISTS audit;

-- ---------------------------------------------------------------------
-- הקשר הבקשה. ה-Interceptor של NestJS מבצע SET LOCAL בתחילת כל טרנזקציה
-- מתוך ה-JWT. ה-pool חייב לרוץ ב-transaction mode כדי שההקשר לא ידלוף
-- בין בקשות.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app_tenant() RETURNS uuid
  LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.current_tenant', true), '')::uuid $$;

CREATE OR REPLACE FUNCTION app_user() RETURNS uuid
  LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.current_user', true), '')::uuid $$;

CREATE OR REPLACE FUNCTION app_role() RETURNS text
  LANGUAGE sql STABLE AS
$$ SELECT COALESCE(NULLIF(current_setting('app.current_role', true), ''), 'agent') $$;

CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger
  LANGUAGE plpgsql AS
$$ BEGIN NEW.updated_at = now(); RETURN NEW; END $$;

-- =====================================================================
-- IDENTITY
-- =====================================================================

CREATE TABLE identity.tenants (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  legal_name        TEXT NOT NULL,
  license_number    TEXT NOT NULL,
  tax_id            TEXT NOT NULL,
  kms_key_arn       TEXT NOT NULL,
  data_region       TEXT NOT NULL DEFAULT 'il-central-1',
  status            TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','suspended','offboarding')),
  retention_policy  JSONB NOT NULL
                    DEFAULT '{"documents_years":7,"raw_files_years":7}'::jsonb,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON COLUMN identity.tenants.kms_key_arn IS
  'CMK ייעודי ל-tenant. מחיקתו היא מנגנון ה-crypto-shredding ב-offboarding.';

CREATE TABLE identity.users (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      UUID NOT NULL REFERENCES identity.tenants(id),
  cognito_sub    TEXT NOT NULL UNIQUE,
  full_name      TEXT NOT NULL,
  email          CITEXT NOT NULL,
  phone_e164     TEXT,
  license_number TEXT,
  license_types  TEXT[] NOT NULL DEFAULT '{}',
  role           TEXT NOT NULL
                 CHECK (role IN ('agent','agency_admin','compliance','support')),
  mfa_enabled    BOOLEAN NOT NULL DEFAULT false,
  last_login_at  TIMESTAMPTZ,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at     TIMESTAMPTZ,
  UNIQUE (tenant_id, email)
);

-- =====================================================================
-- CLIENTS
-- =====================================================================

CREATE TABLE clients.clients (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          UUID NOT NULL REFERENCES identity.tenants(id),
  owner_user_id      UUID REFERENCES identity.users(id),

  -- ת"ז לעולם לא נשמרת גלויה. החיפוש מתבצע על ה-HMAC בלבד, שהוא
  -- דטרמיניסטי (ניתן לאינדוקס), חד-כיווני, ומפתחו per-tenant — כך שלא
  -- ניתן להצליב לקוחות בין סוכנויות.
  national_id_enc    BYTEA NOT NULL,
  national_id_hash   BYTEA NOT NULL,
  national_id_last4  TEXT  NOT NULL,

  first_name         TEXT NOT NULL,
  last_name          TEXT NOT NULL,
  birth_date         DATE,
  gender             TEXT CHECK (gender IN ('m','f','other','unspecified')),
  marital_status     TEXT,
  phone_e164         TEXT,
  email              CITEXT,
  address            JSONB,
  employment         JSONB,
  financial_profile  JSONB,
  health_declaration JSONB,          -- מידע רגיש בהגדרת חוק הגנת הפרטיות

  status             TEXT NOT NULL DEFAULT 'active',
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at         TIMESTAMPTZ,
  UNIQUE (tenant_id, national_id_hash)
);
CREATE INDEX clients_name_idx ON clients.clients (tenant_id, last_name, first_name)
  WHERE deleted_at IS NULL;
CREATE INDEX clients_name_trgm_idx ON clients.clients
  USING gin ((first_name || ' ' || last_name) gin_trgm_ops);
CREATE TRIGGER clients_touch BEFORE UPDATE ON clients.clients
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TABLE clients.family_members (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL,
  client_id       UUID NOT NULL REFERENCES clients.clients(id) ON DELETE CASCADE,
  relation        TEXT NOT NULL CHECK (relation IN
                  ('spouse','child','parent','sibling','common_law_partner','other')),
  first_name      TEXT NOT NULL,
  last_name       TEXT,
  national_id_enc BYTEA,
  birth_date      DATE,
  is_dependent    BOOLEAN NOT NULL DEFAULT false,
  is_insured      BOOLEAN NOT NULL DEFAULT false,
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX family_client_idx ON clients.family_members (tenant_id, client_id);

CREATE TABLE clients.consents (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL,
  client_id       UUID NOT NULL REFERENCES clients.clients(id),
  consent_type    TEXT NOT NULL CHECK (consent_type IN
                  ('clearing_poa','data_processing','marketing','har_habituach')),
  scope           JSONB NOT NULL DEFAULT '{}'::jsonb,
  granted_at      TIMESTAMPTZ NOT NULL,
  expires_at      TIMESTAMPTZ,
  revoked_at      TIMESTAMPTZ,
  evidence_s3_key TEXT,
  evidence_sha256 BYTEA,
  created_by      UUID REFERENCES identity.users(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX consents_active_idx ON clients.consents (client_id, consent_type)
  WHERE revoked_at IS NULL;

CREATE TABLE clients.interactions (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      UUID NOT NULL,
  client_id      UUID NOT NULL REFERENCES clients.clients(id),
  user_id        UUID REFERENCES identity.users(id),
  type           TEXT NOT NULL CHECK (type IN
                 ('meeting','call','whatsapp','email','system_event','note','task')),
  direction      TEXT CHECK (direction IN ('inbound','outbound','internal')),
  subject        TEXT,
  body           TEXT,
  related_entity TEXT,
  related_id     UUID,
  occurred_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  due_at         TIMESTAMPTZ,
  completed_at   TIMESTAMPTZ
);
CREATE INDEX interactions_timeline_idx
  ON clients.interactions (tenant_id, client_id, occurred_at DESC);

-- =====================================================================
-- CLEARING
-- =====================================================================

-- טבלת ייחוס גלובלית — ללא tenant_id, ללא RLS
CREATE TABLE clearing.providers (
  code            TEXT PRIMARY KEY,
  name_he         TEXT NOT NULL,
  provider_type   TEXT NOT NULL CHECK (provider_type IN
                  ('insurer','pension_fund','provident','investment_house')),
  standard_quirks JSONB NOT NULL DEFAULT '{}'::jsonb,
  is_active       BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE clearing.requests (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL,
  client_id       UUID NOT NULL REFERENCES clients.clients(id),
  requested_by    UUID NOT NULL REFERENCES identity.users(id),
  consent_id      UUID NOT NULL REFERENCES clients.consents(id),
  request_type    TEXT NOT NULL CHECK (request_type IN
                  ('full','partial','specific_provider')),
  external_ref    TEXT,
  status          TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                  ('draft','submitted','in_progress','partial','completed',
                   'failed','expired')),
  submitted_at    TIMESTAMPTZ,
  completed_at    TIMESTAMPTZ,
  next_poll_at    TIMESTAMPTZ,
  poll_attempts   INT NOT NULL DEFAULT 0,
  cost_agorot     INT,
  error           JSONB,
  idempotency_key TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, idempotency_key)
);
-- Partial index: ה-Saga סורקת רק בקשות פתוחות
CREATE INDEX requests_poll_idx ON clearing.requests (next_poll_at)
  WHERE status IN ('submitted','in_progress','partial');

CREATE TABLE clearing.files (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL,
  request_id        UUID NOT NULL REFERENCES clearing.requests(id),
  provider_code     TEXT REFERENCES clearing.providers(code),
  s3_bucket         TEXT NOT NULL,
  s3_key            TEXT NOT NULL,
  original_name     TEXT,
  size_bytes        BIGINT,
  sha256            BYTEA NOT NULL,
  declared_encoding TEXT,
  detected_encoding TEXT,
  standard_version  TEXT,
  status            TEXT NOT NULL DEFAULT 'landed' CHECK (status IN
                    ('landed','sanitized','parsed','no_data','quarantined','failed')),
  received_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, sha256)          -- דדופליקציה טבעית
);

CREATE TABLE clearing.parse_jobs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL,
  file_id         UUID NOT NULL REFERENCES clearing.files(id),
  status          TEXT NOT NULL DEFAULT 'queued' CHECK (status IN
                  ('queued','running','succeeded','partial','no_data','failed',
                   'quarantined')),
  parser_version  TEXT NOT NULL,
  mapping_version TEXT,
  sanitize_report JSONB,
  stats           JSONB,
  started_at      TIMESTAMPTZ,
  finished_at     TIMESTAMPTZ,
  duration_ms     INT
);
CREATE INDEX parse_jobs_file_idx ON clearing.parse_jobs (tenant_id, file_id);

CREATE TABLE clearing.parse_issues (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id       UUID NOT NULL,
  parse_job_id    UUID NOT NULL REFERENCES clearing.parse_jobs(id) ON DELETE CASCADE,
  severity        TEXT NOT NULL CHECK (severity IN ('info','warning','error','blocker')),
  code            TEXT NOT NULL,
  canonical_field TEXT,
  xpath           TEXT,
  raw_value       TEXT,
  message_he      TEXT NOT NULL,
  entity_ref      TEXT,
  context         JSONB NOT NULL DEFAULT '{}'::jsonb,
  resolved_at     TIMESTAMPTZ,
  resolved_by     UUID REFERENCES identity.users(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- מסך "מרכז חריגים" — רק מה שעדיין פתוח
CREATE INDEX parse_issues_open_idx ON clearing.parse_issues (tenant_id, severity)
  WHERE resolved_at IS NULL;

-- מיפוי מונחה-דאטה: שינוי מיפוי אינו Deploy
CREATE TABLE clearing.field_mappings (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_field  TEXT NOT NULL,
  standard_version TEXT NOT NULL,
  provider_code    TEXT NOT NULL DEFAULT '*',
  xpath            TEXT NOT NULL,
  fallback_xpaths  TEXT[] NOT NULL DEFAULT '{}',
  data_type        TEXT NOT NULL,
  transform_args   JSONB NOT NULL DEFAULT '{}'::jsonb,
  code_table       TEXT,
  validation       JSONB,
  on_missing       TEXT NOT NULL DEFAULT 'null'
                   CHECK (on_missing IN ('null','flag_for_review','reject')),
  required_for     TEXT[] NOT NULL DEFAULT '{}',
  label_he         TEXT,
  effective_from   DATE NOT NULL DEFAULT CURRENT_DATE,
  effective_to     DATE,
  UNIQUE (canonical_field, standard_version, provider_code, effective_from)
);

-- =====================================================================
-- PORTFOLIO — השכבה הקנונית
-- =====================================================================

CREATE TABLE portfolio.products (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL,
  client_id         UUID NOT NULL REFERENCES clients.clients(id),
  provider_code     TEXT NOT NULL REFERENCES clearing.providers(code),
  source_file_id    UUID REFERENCES clearing.files(id),

  product_type      TEXT NOT NULL CHECK (product_type IN (
                    'pension_comprehensive','pension_general','pension_old',
                    'provident_fund','study_fund','managers_insurance',
                    'provident_investment','other','unknown')),
  policy_number     TEXT NOT NULL,
  product_name      TEXT,
  employer_name     TEXT,
  join_date         DATE,
  status            TEXT NOT NULL DEFAULT 'unknown' CHECK (status IN
                    ('active','paid_up','frozen','closed','unknown')),
  is_dormant        BOOLEAN NOT NULL DEFAULT false,

  -- דגלים שמזינים את חוקי הסיכון החוסמים (R-PEN-001 ואילך)
  has_guaranteed_annuity_factor BOOLEAN,
  guaranteed_factor_value       NUMERIC(8,4),
  is_pre_2013                   BOOLEAN,
  medical_underwriting_notes    JSONB,

  track_code        TEXT,
  track_name        TEXT,
  report_date       DATE NOT NULL,
  data_completeness NUMERIC(4,3) CHECK (data_completeness BETWEEN 0 AND 1),
  provenance        JSONB NOT NULL DEFAULT '{}'::jsonb,
  raw               JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, client_id, provider_code, policy_number, product_type)
);
CREATE INDEX products_client_idx ON portfolio.products (tenant_id, client_id)
  WHERE status <> 'closed';
COMMENT ON COLUMN portfolio.products.provenance IS
  'מאיזה XPath הגיע כל שדה + הערך הגולמי. דרישת ציות: בביקורת חייבים להראות '
  'את מקור כל מספר שמופיע בטבלת ההשוואה במסמך ההנמקה.';

CREATE TABLE portfolio.product_balances (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           UUID NOT NULL,
  product_id          UUID NOT NULL REFERENCES portfolio.products(id) ON DELETE CASCADE,
  as_of_date          DATE NOT NULL,
  total_balance       NUMERIC(14,2),
  employee_component  NUMERIC(14,2),
  employer_component  NUMERIC(14,2),
  severance_component NUMERIC(14,2),
  taxable_split       JSONB,
  ytd_yield_pct       NUMERIC(6,3),
  yield_3y_pct        NUMERIC(6,3),
  UNIQUE (product_id, as_of_date)
);

CREATE TABLE portfolio.product_fees (
  id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id                   UUID NOT NULL,
  product_id                  UUID NOT NULL REFERENCES portfolio.products(id) ON DELETE CASCADE,
  as_of_date                  DATE NOT NULL,
  fee_on_deposit_pct          NUMERIC(6,3),
  fee_on_balance_pct          NUMERIC(6,3),
  fee_expenses_pct            NUMERIC(6,3),
  fee_agreement_end           DATE,
  regulatory_cap_deposit_pct  NUMERIC(6,3),
  regulatory_cap_balance_pct  NUMERIC(6,3),
  is_promotional              BOOLEAN NOT NULL DEFAULT false,
  UNIQUE (product_id, as_of_date)
);
COMMENT ON COLUMN portfolio.product_fees.fee_agreement_end IS
  'מועד סיום הטבת דמי ניהול — נדרש להצגה בהנמקה, אחרת ההשוואה מטעה.';

CREATE TABLE portfolio.investment_tracks (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      UUID NOT NULL,
  product_id     UUID NOT NULL REFERENCES portfolio.products(id) ON DELETE CASCADE,
  track_code     TEXT,
  track_name     TEXT,
  allocation_pct NUMERIC(6,3),
  is_age_based   BOOLEAN,
  risk_level     TEXT
);

CREATE TABLE portfolio.policies (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL,
  client_id         UUID NOT NULL REFERENCES clients.clients(id),
  provider_code     TEXT NOT NULL REFERENCES clearing.providers(code),
  policy_number     TEXT NOT NULL,
  policy_type       TEXT NOT NULL CHECK (policy_type IN
                    ('health','ltc','life_risk','personal_accident','disability',
                     'travel','other')),
  insured_member_id UUID REFERENCES clients.family_members(id),
  start_date        DATE,
  end_date          DATE,
  status            TEXT NOT NULL DEFAULT 'active',
  monthly_premium   NUMERIC(12,2),
  premium_track     TEXT,
  source            TEXT NOT NULL CHECK (source IN
                    ('clearing','har_habituach','manual')),
  source_ref        TEXT,
  generation_note   TEXT,
  raw               JSONB NOT NULL DEFAULT '{}'::jsonb,
  report_date       DATE NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, client_id, provider_code, policy_number)
);
COMMENT ON COLUMN portfolio.policies.generation_note IS
  '"דור" הפוליסה — מזין את R-INS-005 (אזהרת החלפת פוליסה בעלת תנאי דור קודם).';

CREATE TABLE portfolio.coverages (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        UUID NOT NULL,
  product_id       UUID REFERENCES portfolio.products(id) ON DELETE CASCADE,
  policy_id        UUID REFERENCES portfolio.policies(id) ON DELETE CASCADE,
  coverage_type    TEXT NOT NULL,
  coverage_name    TEXT,
  sum_insured      NUMERIC(14,2),
  monthly_benefit  NUMERIC(12,2),
  cost_monthly     NUMERIC(12,2),
  waiting_period_m INT,
  exclusions       JSONB,
  is_active        BOOLEAN NOT NULL DEFAULT true,
  -- כיסוי שייך למוצר פנסיוני או לפוליסת פרט — לא לשניהם ולא לאף אחד
  CHECK (num_nonnulls(product_id, policy_id) = 1)
);

CREATE TABLE portfolio.beneficiaries (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id  UUID NOT NULL,
  product_id UUID REFERENCES portfolio.products(id) ON DELETE CASCADE,
  policy_id  UUID REFERENCES portfolio.policies(id) ON DELETE CASCADE,
  full_name  TEXT,
  relation   TEXT,
  share_pct  NUMERIC(5,2),
  updated_on DATE,
  CHECK (num_nonnulls(product_id, policy_id) = 1)
);

CREATE TABLE portfolio.deposits (
  id            BIGINT GENERATED ALWAYS AS IDENTITY,
  tenant_id     UUID NOT NULL,
  product_id    UUID NOT NULL,
  month         DATE NOT NULL,
  employee_amt  NUMERIC(12,2),
  employer_amt  NUMERIC(12,2),
  severance_amt NUMERIC(12,2),
  salary_base   NUMERIC(12,2),
  PRIMARY KEY (id, month)
) PARTITION BY RANGE (month);
CREATE TABLE portfolio.deposits_default PARTITION OF portfolio.deposits DEFAULT;

-- ---------------------------------------------------------------------
-- Snapshots — לב הציות. Immutable ברמת מסד הנתונים, לא ברמת האפליקציה.
-- ---------------------------------------------------------------------
CREATE TABLE portfolio.snapshots (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL,
  client_id       UUID NOT NULL REFERENCES clients.clients(id),
  created_by      UUID NOT NULL REFERENCES identity.users(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload         JSONB NOT NULL,
  payload_sha256  BYTEA NOT NULL,
  source_file_ids UUID[] NOT NULL DEFAULT '{}',
  source_sha256s  BYTEA[] NOT NULL DEFAULT '{}',
  parser_version  TEXT NOT NULL,
  mapping_version TEXT NOT NULL,
  completeness    JSONB NOT NULL DEFAULT '{}'::jsonb,
  is_locked       BOOLEAN NOT NULL DEFAULT true
);
CREATE INDEX snapshots_client_idx ON portfolio.snapshots (tenant_id, client_id, created_at DESC);

-- אכיפה ברמת ה-DB: קליטת נתונים חדשה לעולם לא משנה המלצה שכבר ניתנה.
CREATE RULE snapshots_no_update AS ON UPDATE TO portfolio.snapshots DO INSTEAD NOTHING;
CREATE RULE snapshots_no_delete AS ON DELETE TO portfolio.snapshots DO INSTEAD NOTHING;

-- =====================================================================
-- RECOMMENDATIONS
-- =====================================================================

CREATE TABLE reco.regulatory_params (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  param_key      TEXT NOT NULL,
  param_value    JSONB NOT NULL,
  source_ref     TEXT NOT NULL,
  effective_from DATE NOT NULL,
  effective_to   DATE,
  version        TEXT NOT NULL,
  UNIQUE (param_key, effective_from)
);
COMMENT ON TABLE reco.regulatory_params IS
  'תקרות דמי ניהול וכל פרמטר רגולטורי אחר — כ-DATA ולא כקוד, כדי ששינוי '
  'רגולציה לא יחייב Deploy. source_ref מפנה לחוזר/תקנה שממנה נגזר הערך.';

CREATE TABLE reco.benchmarks (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider_code       TEXT NOT NULL,
  product_type        TEXT NOT NULL,
  track_code          TEXT,
  period              DATE NOT NULL,
  yield_pct           NUMERIC(6,3),
  yield_3y_pct        NUMERIC(6,3),
  yield_5y_pct        NUMERIC(6,3),
  avg_fee_deposit_pct NUMERIC(6,3),
  avg_fee_balance_pct NUMERIC(6,3),
  sharpe              NUMERIC(6,3),
  UNIQUE (provider_code, product_type, track_code, period)
);

CREATE TABLE reco.recommendations (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id            UUID NOT NULL,
  client_id            UUID NOT NULL REFERENCES clients.clients(id),
  snapshot_id          UUID NOT NULL REFERENCES portfolio.snapshots(id),
  agent_id             UUID NOT NULL REFERENCES identity.users(id),
  status               TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                       ('draft','blocked','ready','document_generated','sent',
                        'signed','cancelled')),
  client_needs         JSONB NOT NULL DEFAULT '{}'::jsonb,
  client_declined_info BOOLEAN NOT NULL DEFAULT false,
  declined_info_impact TEXT,
  agent_disclosure     JSONB NOT NULL DEFAULT '{}'::jsonb,
  rules_version        TEXT NOT NULL,
  reg_params_version   TEXT NOT NULL,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- דרישת התקנות: אם הלקוח סירב למסור מידע, חובה לתעד את השפעת אי-המסירה
  CHECK (NOT client_declined_info OR declined_info_impact IS NOT NULL)
);

CREATE TABLE reco.moves (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id            UUID NOT NULL,
  recommendation_id    UUID NOT NULL REFERENCES reco.recommendations(id) ON DELETE CASCADE,
  move_type            TEXT NOT NULL CHECK (move_type IN
                       ('transfer','new_product','track_change','fee_change',
                        'coverage_add','coverage_change','coverage_cancel','no_change')),
  source_product_id    UUID REFERENCES portfolio.products(id),
  source_policy_id     UUID REFERENCES portfolio.policies(id),
  target_provider_code TEXT REFERENCES clearing.providers(code),
  target_spec          JSONB NOT NULL DEFAULT '{}'::jsonb,
  rationale_codes      TEXT[] NOT NULL DEFAULT '{}',
  rationale_free_text  TEXT,
  amount_estimate      NUMERIC(14,2),
  sort_order           INT NOT NULL DEFAULT 0
);

CREATE TABLE reco.flags (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL,
  recommendation_id UUID NOT NULL REFERENCES reco.recommendations(id) ON DELETE CASCADE,
  move_id           UUID REFERENCES reco.moves(id) ON DELETE CASCADE,
  rule_id           TEXT NOT NULL,
  severity          TEXT NOT NULL CHECK (severity IN
                    ('info','warning','critical','blocker')),
  message_he        TEXT NOT NULL,
  requires_ack      BOOLEAN NOT NULL DEFAULT false,
  agent_ack_at      TIMESTAMPTZ,
  agent_ack_text    TEXT,
  client_ack_at     TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- אזהרה חוסמת שלא טופלה — השאילתה שחוסמת את כפתור "הפק מסמך הנמקה"
CREATE INDEX flags_open_blockers_idx ON reco.flags (tenant_id, recommendation_id)
  WHERE severity = 'blocker' AND agent_ack_at IS NULL;

CREATE TABLE reco.comparison_lines (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL,
  recommendation_id UUID NOT NULL REFERENCES reco.recommendations(id) ON DELETE CASCADE,
  section           TEXT NOT NULL CHECK (section IN ('fees','coverage','yield','track')),
  label_he          TEXT NOT NULL,
  current_value     JSONB,
  proposed_value    JSONB,
  benchmark_value   JSONB,
  delta             JSONB,
  unit              TEXT,
  sort_order        INT NOT NULL DEFAULT 0
);

-- =====================================================================
-- DOCUMENTS & SIGNATURES
-- =====================================================================

CREATE TABLE docs.documents (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL,
  client_id         UUID NOT NULL REFERENCES clients.clients(id),
  recommendation_id UUID REFERENCES reco.recommendations(id),
  doc_type          TEXT NOT NULL CHECK (doc_type IN
                    ('reasoning','disclosure','poa','consent','other')),
  title             TEXT NOT NULL,
  current_version_id UUID,
  supersedes_id     UUID REFERENCES docs.documents(id),
  status            TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                    ('draft','generated','sent','signed','void','superseded')),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE docs.document_versions (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        UUID NOT NULL,
  document_id      UUID NOT NULL REFERENCES docs.documents(id),
  version_no       INT NOT NULL,
  template_id      TEXT NOT NULL,
  template_version TEXT NOT NULL,
  content_model    JSONB NOT NULL,
  s3_key           TEXT NOT NULL,
  sha256           BYTEA NOT NULL,
  page_count       INT,
  rendered_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  is_locked        BOOLEAN NOT NULL DEFAULT false,
  UNIQUE (document_id, version_no)
);
COMMENT ON COLUMN docs.document_versions.content_model IS
  'הקלט המדויק לרינדור. מאפשר לשחזר את המסמך בייט-בייט בביקורת, גם שנים אחרי.';

ALTER TABLE docs.documents
  ADD CONSTRAINT documents_current_version_fk
  FOREIGN KEY (current_version_id) REFERENCES docs.document_versions(id);

CREATE TABLE sign.envelopes (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           UUID NOT NULL,
  document_version_id UUID NOT NULL REFERENCES docs.document_versions(id),
  created_by          UUID NOT NULL REFERENCES identity.users(id),
  token_hash          BYTEA NOT NULL UNIQUE,   -- הטוקן עצמו לא נשמר לעולם
  channel             TEXT NOT NULL CHECK (channel IN
                      ('sms','whatsapp','email','in_person')),
  status              TEXT NOT NULL DEFAULT 'created' CHECK (status IN
                      ('created','sent','delivered','opened','identified','signed',
                       'declined','expired','cancelled')),
  expires_at          TIMESTAMPTZ NOT NULL,
  signed_at           TIMESTAMPTZ,
  signed_s3_key       TEXT,
  signed_sha256       BYTEA,
  tsa_token           BYTEA,
  evidence            JSONB,
  reminders_sent      INT NOT NULL DEFAULT 0,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX envelopes_pending_idx ON sign.envelopes (expires_at)
  WHERE status IN ('sent','delivered','opened','identified');

CREATE TABLE sign.signers (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id              UUID NOT NULL,
  envelope_id            UUID NOT NULL REFERENCES sign.envelopes(id) ON DELETE CASCADE,
  role                   TEXT NOT NULL CHECK (role IN
                         ('client','agent','spouse','guardian')),
  full_name              TEXT NOT NULL,
  phone_e164             TEXT,
  national_id_last4      TEXT,
  signed_at              TIMESTAMPTZ,
  signature_image_s3_key TEXT,
  signature_image_sha256 BYTEA
);

CREATE TABLE sign.events (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id   UUID NOT NULL,
  envelope_id UUID NOT NULL REFERENCES sign.envelopes(id),
  event_type  TEXT NOT NULL CHECK (event_type IN
              ('sent','delivered','opened','otp_sent','otp_failed','otp_verified',
               'id_failed','scrolled_end','signed','declined','expired')),
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ip_address  INET,
  user_agent  TEXT,
  geo_country TEXT,
  metadata    JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX sign_events_envelope_idx ON sign.events (envelope_id, occurred_at);

-- =====================================================================
-- AUDIT — append-only, מחולק לפי חודש, שמירה 24 חודשים לפחות
-- =====================================================================

CREATE TABLE audit.logs (
  id            BIGINT GENERATED ALWAYS AS IDENTITY,
  tenant_id     UUID NOT NULL,
  actor_user_id UUID,
  actor_type    TEXT NOT NULL DEFAULT 'user'
                CHECK (actor_type IN ('user','system','worker','support')),
  action        TEXT NOT NULL,      -- READ | CREATE | UPDATE | EXPORT | SIGN | LOGIN
  entity_type   TEXT NOT NULL,
  entity_id     UUID,
  client_id     UUID,               -- למי שייך המידע שניגשו אליו
  ip_address    INET,
  user_agent    TEXT,
  request_id    TEXT,
  before        JSONB,
  after         JSONB,
  occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (id, occurred_at)
) PARTITION BY RANGE (occurred_at);
CREATE TABLE audit.logs_default PARTITION OF audit.logs DEFAULT;
CREATE INDEX audit_client_idx ON audit.logs (tenant_id, client_id, occurred_at DESC);
COMMENT ON TABLE audit.logs IS
  'כולל פעולות READ ולא רק שינויים — תיעוד גישה למידע הוא דרישה מפורשת '
  'בתקנות הגנת הפרטיות (אבטחת מידע). שמירה: 24 חודשים לפחות.';

COMMIT;
