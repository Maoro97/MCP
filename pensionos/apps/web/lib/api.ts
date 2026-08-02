import 'server-only';

/**
 * שכבת הגישה ל-API. רצה **רק בצד השרת** — הטוקן לעולם לא מגיע לדפדפן.
 *
 * ⚠️ בפיתוח הטוקן מונפק מול /v1/auth/dev-login. בייצור המשתמש מתחבר
 *    ל-Cognito, והטוקן מגיע מה-session cookie. נקודת ההחלפה היחידה היא
 *    `getToken()` — שאר הקובץ לא משתנה.
 */

const API_URL = process.env.API_URL ?? 'http://127.0.0.1:8080';

export interface FieldSource {
  label: string;
  providerName: string | null;
  reportDate: string | null;
  raw: string | null;
  xpath: string | null;
  confidence: number;
  fixes: string[];
  origin: 'clearing' | 'manual';
}

export interface Coverage {
  coverageType: string;
  coverageTypeHe: string;
  coverageName: string | null;
  sumInsured: number | null;
  monthlyBenefit: number | null;
  costMonthly: number | null;
  waitingPeriodM: number | null;
}

export interface Product {
  id: string;
  providerCode: string | null;
  providerName: string | null;
  policyNumber: string | null;
  productType: string;
  productTypeHe: string;
  productName: string | null;
  employerName: string | null;
  joinDate: string | null;
  status: string;
  isDormant: boolean;
  reportDate: string | null;
  totalBalance: number | null;
  employeeComponent: number | null;
  employerComponent: number | null;
  severanceComponent: number | null;
  ytdYieldPct: number | null;
  feeOnDepositPct: number | null;
  feeOnBalancePct: number | null;
  feeAgreementEnd: string | null;
  trackName: string | null;
  hasGuaranteedAnnuityFactor: boolean | null;
  guaranteedFactorValue: number | null;
  isPre2013: boolean | null;
  dataCompleteness: number;
  coverages: Coverage[];
  beneficiaries: { fullName: string | null; relation: string | null; sharePct: number | null }[];
  sources: Record<string, FieldSource>;
}

export interface Advisory {
  ruleId: string;
  severity: 'info' | 'warning' | 'critical';
  message: string;
  entityRef: string | null;
}

export interface Portfolio {
  client: {
    id: string;
    firstName: string;
    lastName: string;
    nationalIdLast4: string;
    birthDate: string | null;
    age: number | null;
    maritalStatus: string | null;
  };
  summary: {
    totalBalance: number | null;
    productsWithoutBalance: number;
    feeOnDepositWeighted: number | null;
    feeOnBalanceWeighted: number | null;
    disabilityMonthly: number | null;
    survivorsMonthly: number | null;
    dataCompleteness: number | null;
    productCount: number;
    dormantCount: number;
  };
  dataAsOf: string | null;
  groups: { pension: Product[]; financial: Product[]; other: Product[] };
  advisories: Advisory[];
  openIssues: {
    id: string;
    severity: string;
    code: string;
    message: string;
    canonicalField: string | null;
    entityRef: string | null;
  }[];
}

export interface ClientSummary {
  id: string;
  firstName: string;
  lastName: string;
  nationalIdLast4: string;
  birthDate: string | null;
  age: number | null;
  phoneE164: string | null;
  productCount: number;
  totalBalance: number | null;
  lastIngestAt: string | null;
}

let cachedToken: { value: string; expiresAt: number } | null = null;

async function getToken(): Promise<string> {
  if (cachedToken && cachedToken.expiresAt > Date.now() + 60_000) {
    return cachedToken.value;
  }
  const res = await fetch(`${API_URL}/v1/auth/dev-login`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      userId: process.env.DEV_USER_ID,
      tenantId: process.env.DEV_TENANT_ID,
      role: process.env.DEV_ROLE ?? 'agency_admin',
    }),
    cache: 'no-store',
  });
  if (!res.ok) throw new Error(`dev-login failed: ${res.status}`);
  const data = (await res.json()) as { accessToken: string; expiresIn: number };
  cachedToken = {
    value: data.accessToken,
    expiresAt: Date.now() + data.expiresIn * 1000,
  };
  return data.accessToken;
}

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { authorization: `Bearer ${await getToken()}` },
    cache: 'no-store', // נתוני תיק לעולם לא נשמרים במטמון
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`API ${res.status} on ${path}: ${body.slice(0, 200)}`);
  }
  return (await res.json()) as T;
}

export const api = {
  listClients: (q?: string) =>
    apiGet<ClientSummary[]>(`/v1/clients${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  getPortfolio: (id: string) => apiGet<Portfolio>(`/v1/clients/${id}/portfolio`),
  parserHealth: () => apiGet<{ parser: string }>('/v1/ingestion/health'),

  async ingest(clientId: string, file: File) {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`${API_URL}/v1/clients/${clientId}/ingest`, {
      method: 'POST',
      headers: { authorization: `Bearer ${await getToken()}` },
      body: form,
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body?.message ?? `שגיאה ${res.status}`);
    return body as {
      status: string;
      productsPersisted: number;
      staleSkipped: number;
      duplicate: boolean;
      blockingIssues: string[];
    };
  },
};
