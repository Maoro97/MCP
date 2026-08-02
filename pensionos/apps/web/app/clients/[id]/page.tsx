import Link from 'next/link';
import { notFound } from 'next/navigation';

import { ProductCard } from '@/components/ProductCard';
import { UploadPanel } from '@/components/UploadPanel';
import { api, type Advisory, type Portfolio } from '@/lib/api';
import { hebrewDate, money, pct, ratio } from '@/lib/format';

import { ingestAction } from './actions';

export const dynamic = 'force-dynamic';

const SEVERITY_STYLE: Record<Advisory['severity'], { icon: string; cls: string }> = {
  critical: { icon: '⚠', cls: 'border-s-risk-high bg-risk-high/5 text-risk-high' },
  warning: { icon: '⚠', cls: 'border-s-risk-med bg-risk-med/5 text-risk-med' },
  info: { icon: 'ℹ', cls: 'border-s-risk-low bg-risk-low/5 text-risk-low' },
};

function Kpi({
  label,
  value,
  hint,
  tone = 'default',
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: 'default' | 'warn';
}) {
  return (
    <div className="rounded-xl border border-surface-line bg-surface px-4 py-3">
      <p className="text-xs text-ink-muted">{label}</p>
      <p
        className={`num mt-1 text-xl font-semibold ${
          tone === 'warn' ? 'text-risk-med' : 'text-ink'
        }`}
      >
        {value}
      </p>
      {hint && <p className="mt-0.5 text-xs text-ink-faint">{hint}</p>}
    </div>
  );
}

function Group({ title, products }: { title: string; products: Portfolio['groups']['pension'] }) {
  if (products.length === 0) return null;
  return (
    <section className="mt-6">
      <h2 className="mb-2 text-sm font-semibold text-ink-muted">
        {title} <span className="num text-ink-faint">({products.length})</span>
      </h2>
      <div className="space-y-3">
        {products.map((p) => (
          <ProductCard key={p.id} product={p} />
        ))}
      </div>
    </section>
  );
}

export default async function ClientPortfolioPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let portfolio: Portfolio;
  try {
    portfolio = await api.getPortfolio(id);
  } catch (err) {
    if (String(err).includes('404')) notFound();
    throw err;
  }

  const { client, summary, advisories, openIssues, groups } = portfolio;
  const totalProducts = groups.pension.length + groups.financial.length + groups.other.length;

  return (
    <main className="mx-auto max-w-5xl px-4 py-6">
      <nav className="mb-4 text-sm">
        <Link href="/clients" className="text-brand hover:underline">
          ← כל הלקוחות
        </Link>
      </nav>

      {/* --- כותרת התיק --- */}
      <header className="rounded-xl border border-surface-line bg-surface p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-2xl font-bold">
              {client.firstName} {client.lastName}
            </h1>
            <span className="text-sm text-ink-muted">
              ת.ז המסתיימת ב־<bdi className="num">{client.nationalIdLast4}</bdi>
            </span>
            {client.age !== null && (
              <span className="text-sm text-ink-muted">
                בן/בת <span className="num">{client.age}</span>
              </span>
            )}
            {client.maritalStatus && (
              <span className="text-sm text-ink-muted">{client.maritalStatus}</span>
            )}
          </div>
          <div className="text-sm text-ink-muted">
            נכון ל־<span className="num">{hebrewDate(portfolio.dataAsOf)}</span>
            {summary.dataCompleteness !== null && (
              <span
                className="ms-3"
                title="שיעור שדות החובה שהתקבלו מהיצרנים, ממוצע על פני כל המוצרים"
              >
                שלמות נתונים{' '}
                <span
                  className={`num font-semibold ${
                    summary.dataCompleteness >= 0.9 ? 'text-risk-ok' : 'text-risk-med'
                  }`}
                >
                  {ratio(summary.dataCompleteness)}
                </span>
              </span>
            )}
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Kpi
            label="סה״כ צבירה"
            value={money(summary.totalBalance)}
            hint={
              summary.productsWithoutBalance > 0
                ? `${summary.productsWithoutBalance} מוצרים ללא יתרה מדווחת`
                : undefined
            }
            tone={summary.productsWithoutBalance > 0 ? 'warn' : 'default'}
          />
          <Kpi
            label="ד״נ מצבירה (משוקלל)"
            value={pct(summary.feeOnBalanceWeighted)}
            hint="משוקלל לפי גודל הצבירה"
          />
          <Kpi
            label="ד״נ מהפקדה (משוקלל)"
            value={pct(summary.feeOnDepositWeighted)}
          />
          <Kpi
            label="כיסוי א.כ.ע חודשי"
            value={money(summary.disabilityMonthly)}
            hint={
              summary.survivorsMonthly !== null
                ? `שאירים: ${money(summary.survivorsMonthly)}`
                : undefined
            }
          />
        </div>
      </header>

      {/* --- הערות --- */}
      {advisories.length > 0 && (
        <section className="mt-5">
          <h2 className="mb-2 text-sm font-semibold text-ink-muted">
            נקודות לתשומת לב <span className="num text-ink-faint">({advisories.length})</span>
          </h2>
          <ul className="space-y-2">
            {advisories.map((a, i) => {
              const s = SEVERITY_STYLE[a.severity];
              return (
                <li
                  key={i}
                  className={`rounded-lg border-s-4 px-3 py-2 text-sm ${s.cls}`}
                >
                  <span className="me-2">{s.icon}</span>
                  {/* <bdi> מבודד את הרצף — בלעדיו תאריך או מספר פוליסה
                      שמוטמעים בטקסט עברי מתהפכים ונדבקים למילה שאחריהם */}
                  <bdi>{a.message}</bdi>
                  {/* המרווח על ה-span החיצוני (RTL) ולא על ה-bdi:
                      ms-* הוא margin-inline-start ונפתר לפי כיוון האלמנט
                      עצמו, ו-.num מגדיר direction:ltr — כך שמרווח שמונח
                      ישירות על ה-bdi נופל בצד ההפוך. */}
                  <span className="ms-2 text-xs opacity-60">
                    <bdi className="num">{a.ruleId}</bdi>
                  </span>
                </li>
              );
            })}
          </ul>
          <p className="mt-2 text-xs text-ink-faint">
            אלה הערות תצוגה בלבד. ההחלטה אם מהלך חסום מתקבלת במנוע החוקים בעת בניית
            ההמלצה, על בסיס צילום תיק נעול.
          </p>
        </section>
      )}

      {/* --- מוצרים --- */}
      {totalProducts === 0 ? (
        <p className="mt-6 rounded-xl border border-dashed border-surface-line bg-surface p-8 text-center text-ink-muted">
          עדיין לא נקלטו נתונים עבור לקוח זה. קלטו קובץ מסלקה כדי לבנות את התיק.
        </p>
      ) : (
        <>
          <Group title="נכסים פנסיוניים" products={groups.pension} />
          <Group title="נכסים פיננסיים" products={groups.financial} />
          <Group title="מוצרים נוספים" products={groups.other} />
        </>
      )}

      {/* --- חריגי קליטה --- */}
      {openIssues.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-2 text-sm font-semibold text-ink-muted">
            חריגי קליטה פתוחים <span className="num text-ink-faint">({openIssues.length})</span>
          </h2>
          <ul className="divide-y divide-surface-line overflow-hidden rounded-xl border border-surface-line bg-surface text-sm">
            {openIssues.map((issue) => (
              <li key={issue.id} className="flex items-start gap-3 px-4 py-2.5">
                <span
                  className={
                    issue.severity === 'blocker' || issue.severity === 'error'
                      ? 'text-risk-high'
                      : 'text-risk-med'
                  }
                >
                  {issue.severity === 'blocker' ? '🛑' : issue.severity === 'error' ? '✖' : '⚠'}
                </span>
                <bdi className="flex-1">{issue.message}</bdi>
                {issue.entityRef && (
                  <span className="text-xs text-ink-faint">
                    <bdi className="num">{issue.entityRef}</bdi>
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="mt-6">
        <UploadPanel clientId={id} action={ingestAction} />
      </div>
    </main>
  );
}
