import type { Product } from '@/lib/api';
import { hebrewDate, isMissing, money, pct, ratio, withinMonths } from '@/lib/format';

import { ValueWithSource } from './ValueWithSource';

function CompletenessBar({ value }: { value: number }) {
  const tone =
    value >= 0.9 ? 'bg-risk-ok' : value >= 0.7 ? 'bg-risk-med' : 'bg-risk-high';
  return (
    <span className="inline-flex items-center gap-2" title="שיעור שדות החובה שהתקבלו">
      <span className="h-1.5 w-16 rounded-full bg-surface-line">
        <span
          className={`block h-full rounded-full ${tone}`}
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </span>
      <span className="num text-xs text-ink-muted">{ratio(value)}</span>
    </span>
  );
}

export function ProductCard({ product: p }: { product: Product }) {
  const feeEnding = withinMonths(p.feeAgreementEnd, 12);
  const missingRequired = isMissing(p.totalBalance) || isMissing(p.feeOnBalancePct);

  return (
    <article
      className={[
        'rounded-xl border bg-surface p-4 transition-shadow hover:shadow-sm',
        p.isDormant ? 'border-surface-line opacity-60' : 'border-surface-line',
        missingRequired ? 'border-s-4 border-s-risk-high' : '',
      ].join(' ')}
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <h3 className="text-base font-semibold text-ink">{p.productTypeHe}</h3>
          <span className="text-ink-muted">· {p.providerName}</span>
          <bdi className="num text-sm text-ink-faint">{p.policyNumber}</bdi>

          {p.hasGuaranteedAnnuityFactor && (
            <span
              className="rounded-md bg-risk-high/10 px-2 py-0.5 text-xs font-medium text-risk-high"
              title={
                'ניוד הכספים יבטל את מקדם הקצבה המובטח ויקטין את הקצבה הצפויה.\n' +
                'מנוע החוקים יחסום ניוד ללא נימוק מפורש והצהרת לקוח (R-PEN-001).'
              }
            >
              🔒 מקדם קצבה מובטח
              {p.guaranteedFactorValue ? ` ${p.guaranteedFactorValue}` : ''}
            </span>
          )}

          {p.isDormant && (
            <span className="rounded-md bg-surface-sunken px-2 py-0.5 text-xs text-ink-muted">
              לא פעיל
            </span>
          )}
          {p.productType === 'unknown' && (
            <span className="rounded-md bg-risk-med/10 px-2 py-0.5 text-xs text-risk-med">
              סוג מוצר לא זוהה
            </span>
          )}
        </div>
        <CompletenessBar value={p.dataCompleteness} />
      </header>

      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
        <div>
          <dt className="text-xs text-ink-muted">יתרה צבורה</dt>
          <dd className="text-lg font-semibold">
            <ValueWithSource value={money(p.totalBalance)} source={p.sources.total_balance} />
          </dd>
        </div>
        <div>
          <dt className="text-xs text-ink-muted">ד&quot;נ מהפקדה</dt>
          <dd>
            <ValueWithSource
              value={pct(p.feeOnDepositPct)}
              source={p.sources.fee_on_deposit_pct}
            />
          </dd>
        </div>
        <div>
          <dt className="text-xs text-ink-muted">ד&quot;נ מצבירה</dt>
          <dd>
            <ValueWithSource
              value={pct(p.feeOnBalancePct)}
              source={p.sources.fee_on_balance_pct}
            />
          </dd>
        </div>
        <div>
          <dt className="text-xs text-ink-muted">תשואה מתחילת שנה</dt>
          <dd>
            <ValueWithSource value={pct(p.ytdYieldPct)} source={p.sources.ytd_yield_pct} />
          </dd>
        </div>
      </dl>

      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-muted">
        {p.trackName && <span>מסלול: {p.trackName}</span>}
        {p.employerName && <span>מעסיק: {p.employerName}</span>}
        <span>
          הצטרפות: <span className="num">{hebrewDate(p.joinDate)}</span>
        </span>
        <span>
          נכון ל: <span className="num">{hebrewDate(p.reportDate)}</span>
        </span>
      </div>

      {feeEnding && (
        <p className="mt-2 rounded-md bg-risk-med/10 px-3 py-1.5 text-xs text-risk-med">
          ⚠ הטבת דמי הניהול מסתיימת ב־
          <bdi className="num">{hebrewDate(p.feeAgreementEnd)}</bdi> — יש להציג זאת
          בהשוואה, אחרת ההשוואה מטעה
        </p>
      )}

      {p.coverages.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2 border-t border-surface-line pt-3">
          {p.coverages.map((c, i) => (
            <li
              key={i}
              className="rounded-lg bg-surface-sunken px-2.5 py-1 text-xs"
              title={
                c.waitingPeriodM !== null ? `תקופת אכשרה: ${c.waitingPeriodM} חודשים` : undefined
              }
            >
              <span className="text-ink-muted">{c.coverageTypeHe}: </span>
              <span className="num font-medium">
                {c.monthlyBenefit !== null
                  ? `${money(c.monthlyBenefit)} לחודש`
                  : money(c.sumInsured)}
              </span>
            </li>
          ))}
        </ul>
      )}

      {p.beneficiaries.length === 0 && !p.isDormant && (
        <p className="mt-2 text-xs text-ink-faint">לא דווחו מוטבים</p>
      )}
    </article>
  );
}
