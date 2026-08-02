/**
 * בדיקות אינטגרציה מול המערכת הרצה (API + Parser + PostgreSQL).
 *
 * הרצה:  pnpm test        (ראה scripts/dev-up.sh להרמת התלויות)
 *
 * הבדיקות כאן מכסות את מה שבדיקות יחידה לא יכולות לתפוס: בידוד Tenant
 * דרך ה-HTTP, ואת כלל ה-Reconcile בין קבצים — באג שהתגלה רק כשחיברנו
 * את המנוע ל-DB, וששקט לחלוטין כשהוא קורה.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { after, before, describe, it } from 'node:test';
import { join } from 'node:path';

const API = process.env.API_URL ?? 'http://127.0.0.1:8080';
const FIXTURES = join(
  import.meta.dirname,
  '../../../services/parser/tests/fixtures',
);

const TENANT_A = '11111111-1111-1111-1111-111111111111';
const USER_A = 'aaaaaaaa-0000-0000-0000-000000000001';
const TENANT_B = '22222222-2222-2222-2222-222222222222';
const USER_B = 'bbbbbbbb-0000-0000-0000-000000000001';

async function login(userId: string, tenantId: string, role = 'agency_admin') {
  const res = await fetch(`${API}/v1/auth/dev-login`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ userId, tenantId, role }),
  });
  assert.equal(res.status, 201, 'dev-login should succeed');
  const { accessToken } = (await res.json()) as { accessToken: string };
  return accessToken;
}

function auth(token: string) {
  return { authorization: `Bearer ${token}` };
}

async function createClient(token: string, nationalId: string, first: string) {
  const res = await fetch(`${API}/v1/clients`, {
    method: 'POST',
    headers: { ...auth(token), 'content-type': 'application/json' },
    body: JSON.stringify({ nationalId, firstName: first, lastName: 'בדיקה' }),
  });
  const body = (await res.json()) as { id?: string; message?: string };
  return { status: res.status, ...body };
}

async function ingest(token: string, clientId: string, fixture: string) {
  const form = new FormData();
  form.append(
    'file',
    new Blob([new Uint8Array(readFileSync(join(FIXTURES, fixture)))]),
    fixture,
  );
  const res = await fetch(`${API}/v1/clients/${clientId}/ingest`, {
    method: 'POST',
    headers: auth(token),
    body: form,
  });
  return (await res.json()) as any;
}

async function portfolio(token: string, clientId: string) {
  const res = await fetch(`${API}/v1/clients/${clientId}/portfolio`, {
    headers: auth(token),
  });
  return { status: res.status, body: res.ok ? await res.json() : null };
}

/** ת"ז ייחודית לכל ריצה, כדי שהבדיקות לא יתנגשו זו בזו. */
function uniqueNationalId(): string {
  for (let attempt = 0; attempt < 1000; attempt++) {
    const base = String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
    for (let d = 0; d < 10; d++) {
      const id = base + d;
      let total = 0;
      for (let i = 0; i < 9; i++) {
        const digit = Number(id[i]) * (i % 2 === 0 ? 1 : 2);
        total += digit < 10 ? digit : digit - 9;
      }
      if (total % 10 === 0) return id;
    }
  }
  throw new Error('could not generate a valid national id');
}

let tokenA = '';

before(async () => {
  const health = await fetch(`${API}/v1/ingestion/health`).catch(() => null);
  assert.ok(health?.ok, `API not reachable at ${API} — run scripts/dev-up.sh`);
  const { parser } = (await health.json()) as { parser: string };
  assert.equal(parser, 'up', 'parser service must be running');
  tokenA = await login(USER_A, TENANT_A);
});

describe('אימות', () => {
  it('בקשה ללא טוקן נדחית', async () => {
    const res = await fetch(`${API}/v1/clients`);
    assert.equal(res.status, 401);
  });

  it('טוקן חתום במפתח אחר נדחה', async () => {
    const res = await fetch(`${API}/v1/clients`, {
      headers: { authorization: 'Bearer eyJhbGciOiJIUzI1NiJ9.e30.invalid' },
    });
    assert.equal(res.status, 401);
  });
});

describe('ולידציה', () => {
  it('ת"ז עם ספרת ביקורת שגויה נדחית', async () => {
    const r = await createClient(tokenA, '039472518', 'שגוי');
    assert.equal(r.status, 400);
    assert.match(r.message ?? '', /ספרת ביקורת/);
  });

  it('לקוח כפול באותה סוכנות נדחה', async () => {
    const id = uniqueNationalId();
    const first = await createClient(tokenA, id, 'ראשון');
    assert.equal(first.status, 201);
    const second = await createClient(tokenA, id, 'שני');
    assert.equal(second.status, 400);
  });
});

describe('בידוד Tenant', () => {
  it('סוכנות אחרת מקבלת 404 על לקוח שאינו שלה', async () => {
    const created = await createClient(tokenA, uniqueNationalId(), 'מבודד');
    assert.equal(created.status, 201);

    const tokenB = await login(USER_B, TENANT_B);
    const { status } = await portfolio(tokenB, created.id!);

    // 404 ולא 403 — קיומו של המשאב אינו מידע שאנחנו מוכנים לדלוף
    assert.equal(status, 404);
  });
});

describe('קליטת קבצים', () => {
  it('קובץ תקין נקלט עם כל המוצרים', async () => {
    const c = await createClient(tokenA, '039472519', 'דנה');
    const clientId =
      c.id ??
      (await (async () => {
        const res = await fetch(`${API}/v1/clients?q=2519`, { headers: auth(tokenA) });
        return ((await res.json()) as any[])[0].id as string;
      })());

    const r = await ingest(tokenA, clientId, '01_clean_menora.xml');
    if (!r.duplicate) {
      assert.equal(r.status, 'succeeded');
      assert.equal(r.productsPersisted, 2);
    }

    const { body } = await portfolio(tokenA, clientId);
    assert.ok(body.groups.pension.length >= 2);

    const managers = body.groups.pension.find(
      (p: any) => p.policyNumber === '8871200',
    );
    assert.equal(managers.hasGuaranteedAnnuityFactor, true);
    assert.equal(managers.guaranteedFactorValue, 167.4);

    // ה-advisory שמזין את R-PEN-001 חייב להופיע
    assert.ok(
      body.advisories.some((a: any) => a.ruleId === 'R-PEN-001'),
      'מקדם קצבה מובטח חייב להופיע כנקודה לתשומת לב',
    );
  });

  it('דיווח ישן או חלקי אינו דורס דיווח טוב', async () => {
    // הבאג: קובץ 04 (תגים ריקים, ללא תאריך נכונות) מכיל את אותה קופה
    // כמו קובץ 01. בלי כלל Reconcile בין קבצים הוא היה מוחק את הנתונים
    // התקינים — בשקט, בלי שגיאה, ובלי שאיש ישים לב.
    const res = await fetch(`${API}/v1/clients?q=2519`, { headers: auth(tokenA) });
    const clientId = ((await res.json()) as any[])[0].id as string;

    const before = await portfolio(tokenA, clientId);
    const beforeProduct = before.body.groups.pension.find(
      (p: any) => p.policyNumber === '5512340' && p.providerName === 'מנורה מבטחים',
    );
    assert.ok(beforeProduct.totalBalance > 0, 'נדרשת יתרה קיימת לפני הבדיקה');

    const r = await ingest(tokenA, clientId, '04_empty_tags_and_zeros.xml');
    if (!r.duplicate) {
      assert.equal(r.productsPersisted, 0, 'אסור לקלוט דיווח נחות');
      assert.equal(r.staleSkipped, 1, 'הדילוג חייב להיות מדווח ולא שקט');
    }

    const after = await portfolio(tokenA, clientId);
    const afterProduct = after.body.groups.pension.find(
      (p: any) => p.policyNumber === '5512340' && p.providerName === 'מנורה מבטחים',
    );
    assert.equal(
      afterProduct.totalBalance,
      beforeProduct.totalBalance,
      'היתרה נדרסה ע"י דיווח חלקי',
    );
    assert.equal(afterProduct.feeOnBalancePct, beforeProduct.feeOnBalancePct);
  });

  it('קובץ של לקוח אחר מועבר להסגר ואינו נכנס לתיק', async () => {
    const res = await fetch(`${API}/v1/clients?q=2519`, { headers: auth(tokenA) });
    const clientId = ((await res.json()) as any[])[0].id as string;

    const r = await ingest(tokenA, clientId, '09_subject_mismatch.xml');
    if (!r.duplicate) {
      assert.equal(r.status, 'quarantined');
      assert.equal(r.productsPersisted, 0);
      assert.ok(r.blockingIssues.some((m: string) => m.includes('אי-התאמה')));
    }
  });

  it('קליטה חוזרת של אותו קובץ אינה מכפילה נתונים', async () => {
    const res = await fetch(`${API}/v1/clients?q=2519`, { headers: auth(tokenA) });
    const clientId = ((await res.json()) as any[])[0].id as string;

    const first = await portfolio(tokenA, clientId);
    await ingest(tokenA, clientId, '01_clean_menora.xml');
    const second = await portfolio(tokenA, clientId);

    assert.equal(
      second.body.summary.productCount,
      first.body.summary.productCount,
    );
  });
});

describe('תצוגת חוסרים', () => {
  it('שדה שלא דווח מוחזר כ-null ולא כאפס', async () => {
    const created = await createClient(tokenA, '021234562', 'אורי');
    const clientId =
      created.id ??
      (await (async () => {
        const res = await fetch(`${API}/v1/clients?q=4562`, { headers: auth(tokenA) });
        return ((await res.json()) as any[])[0].id as string;
      })());

    await ingest(tokenA, clientId, '16_other_client_sparse.xml');
    const { body } = await portfolio(tokenA, clientId);
    const product = body.groups.financial[0];

    assert.equal(product.totalBalance, null, 'יתרה חסרה חייבת להיות null');
    assert.equal(product.feeOnBalancePct, null);
    assert.notEqual(product.totalBalance, 0, 'אסור להציג חוסר כאפס');
    assert.ok(
      body.advisories.some((a: any) => a.ruleId === 'R-DAT-008'),
      'חוסר בנתון חובה חייב להופיע כהערה',
    );
  });
});

after(() => {
  // אין ניקוי: הבדיקות אידמפוטנטיות ומשתמשות בדדופליקציה של המערכת.
});
