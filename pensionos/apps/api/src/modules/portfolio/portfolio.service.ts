import { Injectable } from '@nestjs/common';

import { AuditService } from '../../common/audit.service';
import type { Principal } from '../../common/principal';
import { DbService, type Tx } from '../../db/db.service';
import { ClientsService } from '../clients/clients.service';

/** ⚠️ אלה **הערות תצוגה** בלבד, לא מנוע החוקים (E6). הן נגזרות מעמודות
 *  שכבר נשמרו, ומטרתן להפנות את תשומת לב הסוכן. ההחלטה אם מהלך חסום
 *  תתקבל במנוע החוקים בזמן בניית ההמלצה, על בסיס Snapshot נעול. */
export interface Advisory {
  ruleId: string;
  severity: 'info' | 'warning' | 'critical';
  message: string;
  entityRef: string | null;
}

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

export interface ProductView {
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
  coverages: {
    coverageType: string;
    coverageTypeHe: string;
    coverageName: string | null;
    sumInsured: number | null;
    monthlyBenefit: number | null;
    costMonthly: number | null;
    waitingPeriodM: number | null;
  }[];
  beneficiaries: { fullName: string | null; relation: string | null; sharePct: number | null }[];
  sources: Record<string, FieldSource>;
}

export interface PortfolioView {
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
  groups: { pension: ProductView[]; financial: ProductView[]; other: ProductView[] };
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

const PRODUCT_TYPE_HE: Record<string, string> = {
  pension_comprehensive: 'קרן פנסיה מקיפה',
  pension_general: 'קרן פנסיה כללית',
  pension_old: 'קרן פנסיה ותיקה',
  provident_fund: 'קופת גמל',
  study_fund: 'קרן השתלמות',
  managers_insurance: 'ביטוח מנהלים',
  provident_investment: 'גמל להשקעה',
  other: 'אחר',
  unknown: 'לא זוהה',
};

const COVERAGE_TYPE_HE: Record<string, string> = {
  disability: 'אובדן כושר עבודה',
  survivors: 'שאירים',
  death: 'ריסק למקרה מוות',
  ltc: 'סיעוד',
  surgery: 'ניתוחים',
  other: 'אחר',
};

const PENSION_TYPES = new Set([
  'pension_comprehensive',
  'pension_general',
  'pension_old',
  'managers_insurance',
]);
const FINANCIAL_TYPES = new Set([
  'provident_fund',
  'study_fund',
  'provident_investment',
]);

const FIELD_LABELS: Record<string, string> = {
  total_balance: 'יתרה צבורה',
  fee_on_deposit_pct: 'דמי ניהול מהפקדה',
  fee_on_balance_pct: 'דמי ניהול מצבירה',
  report_date: 'תאריך נכונות הנתונים',
  join_date: 'תאריך הצטרפות',
  ytd_yield_pct: 'תשואה מתחילת שנה',
  track_name: 'מסלול השקעה',
  guaranteed_factor_value: 'מקדם קצבה מובטח',
};

function num(value: unknown): number | null {
  return value === null || value === undefined ? null : Number(value);
}

function iso(value: unknown): string | null {
  return value ? new Date(value as string).toISOString().slice(0, 10) : null;
}

@Injectable()
export class PortfolioService {
  constructor(
    private readonly db: DbService,
    private readonly clients: ClientsService,
    private readonly audit: AuditService,
  ) {}

  async getPortfolio(principal: Principal, clientId: string): Promise<PortfolioView> {
    return this.db.withTenant(principal, async (tx) => {
      await this.clients.requireClient(tx, clientId);

      const [client] = await tx<any[]>`
        SELECT id, first_name, last_name, national_id_last4, birth_date, marital_status
        FROM clients.clients WHERE id = ${clientId}
      `;

      const products = await this.loadProducts(tx, clientId);
      const issues = await this.loadOpenIssues(tx, clientId);

      await this.audit.record(tx, principal, {
        action: 'READ',
        entityType: 'portfolio',
        entityId: clientId,
        clientId,
        after: { products: products.length },
      });

      const groups = {
        pension: products.filter((p) => PENSION_TYPES.has(p.productType)),
        financial: products.filter((p) => FINANCIAL_TYPES.has(p.productType)),
        other: products.filter(
          (p) => !PENSION_TYPES.has(p.productType) && !FINANCIAL_TYPES.has(p.productType),
        ),
      };

      return {
        client: {
          id: client.id,
          firstName: client.first_name,
          lastName: client.last_name,
          nationalIdLast4: client.national_id_last4,
          birthDate: iso(client.birth_date),
          age: this.age(client.birth_date),
          maritalStatus: client.marital_status,
        },
        summary: this.summarize(products),
        dataAsOf: this.latestReportDate(products),
        groups,
        advisories: this.advisories(products),
        openIssues: issues,
      };
    });
  }

  // ------------------------------------------------------------------

  private async loadProducts(tx: Tx, clientId: string): Promise<ProductView[]> {
    const rows = await tx<any[]>`
      SELECT p.*,
             pr.name_he AS provider_name_he,
             f.source   AS file_source,
             b.total_balance, b.employee_component, b.employer_component,
             b.severance_component, b.ytd_yield_pct,
             fe.fee_on_deposit_pct, fe.fee_on_balance_pct, fe.fee_agreement_end
      FROM portfolio.products p
      LEFT JOIN clearing.providers pr ON pr.code = p.provider_code
      LEFT JOIN clearing.files     f  ON f.id = p.source_file_id
      LEFT JOIN LATERAL (
        SELECT * FROM portfolio.product_balances
        WHERE product_id = p.id ORDER BY as_of_date DESC LIMIT 1
      ) b ON true
      LEFT JOIN LATERAL (
        SELECT * FROM portfolio.product_fees
        WHERE product_id = p.id ORDER BY as_of_date DESC LIMIT 1
      ) fe ON true
      WHERE p.client_id = ${clientId} AND p.status <> 'closed'
      ORDER BY p.is_dormant, b.total_balance DESC NULLS LAST
    `;

    if (rows.length === 0) return [];
    const ids = rows.map((r) => r.id);

    const coverages = await tx<any[]>`
      SELECT * FROM portfolio.coverages WHERE product_id = ANY(${ids}::uuid[])
    `;
    const beneficiaries = await tx<any[]>`
      SELECT * FROM portfolio.beneficiaries WHERE product_id = ANY(${ids}::uuid[])
    `;

    return rows.map((r) => this.toProductView(r, coverages, beneficiaries));
  }

  private toProductView(r: any, coverages: any[], beneficiaries: any[]): ProductView {
    const provenance: Record<string, any> = r.provenance ?? {};
    const reportDate = iso(r.report_date);
    const origin: 'clearing' | 'manual' =
      r.file_source === 'manual_upload' ? 'manual' : 'clearing';

    const sources: Record<string, FieldSource> = {};
    for (const [field, meta] of Object.entries(provenance)) {
      sources[field] = {
        label: FIELD_LABELS[field] ?? field,
        providerName: r.provider_name_he ?? r.provider_code,
        reportDate,
        raw: (meta as any)?.raw ?? null,
        xpath: (meta as any)?.xpath ?? null,
        confidence: (meta as any)?.confidence ?? 1,
        fixes: (meta as any)?.fixes ?? [],
        origin,
      };
    }

    return {
      id: r.id,
      providerCode: r.provider_code,
      providerName: r.provider_name_he ?? r.provider_code,
      policyNumber: r.policy_number,
      productType: r.product_type,
      productTypeHe: PRODUCT_TYPE_HE[r.product_type] ?? r.product_type,
      productName: r.product_name,
      employerName: r.employer_name,
      joinDate: iso(r.join_date),
      status: r.status,
      isDormant: r.is_dormant,
      reportDate,
      totalBalance: num(r.total_balance),
      employeeComponent: num(r.employee_component),
      employerComponent: num(r.employer_component),
      severanceComponent: num(r.severance_component),
      ytdYieldPct: num(r.ytd_yield_pct),
      feeOnDepositPct: num(r.fee_on_deposit_pct),
      feeOnBalancePct: num(r.fee_on_balance_pct),
      feeAgreementEnd: iso(r.fee_agreement_end),
      trackName: r.track_name,
      hasGuaranteedAnnuityFactor: r.has_guaranteed_annuity_factor,
      guaranteedFactorValue: num(r.guaranteed_factor_value),
      isPre2013: r.is_pre_2013,
      dataCompleteness: Number(r.data_completeness ?? 0),
      coverages: coverages
        .filter((c) => c.product_id === r.id)
        .map((c) => ({
          coverageType: c.coverage_type,
          coverageTypeHe: COVERAGE_TYPE_HE[c.coverage_type] ?? c.coverage_type,
          coverageName: c.coverage_name,
          sumInsured: num(c.sum_insured),
          monthlyBenefit: num(c.monthly_benefit),
          costMonthly: num(c.cost_monthly),
          waitingPeriodM: c.waiting_period_m,
        })),
      beneficiaries: beneficiaries
        .filter((b) => b.product_id === r.id)
        .map((b) => ({
          fullName: b.full_name,
          relation: b.relation,
          sharePct: num(b.share_pct),
        })),
      sources,
    };
  }

  private async loadOpenIssues(tx: Tx, clientId: string) {
    const rows = await tx<any[]>`
      SELECT i.id, i.severity, i.code, i.message_he, i.canonical_field, i.entity_ref
      FROM clearing.parse_issues i
      JOIN clearing.parse_jobs j ON j.id = i.parse_job_id
      JOIN clearing.files     f ON f.id = j.file_id
      WHERE f.client_id = ${clientId}
        AND i.resolved_at IS NULL
        AND i.severity IN ('warning','error','blocker')
      ORDER BY CASE i.severity
                 WHEN 'blocker' THEN 0 WHEN 'error' THEN 1 ELSE 2 END,
               i.created_at DESC
      LIMIT 100
    `;
    return rows.map((r) => ({
      id: String(r.id),
      severity: r.severity,
      code: r.code,
      message: r.message_he,
      canonicalField: r.canonical_field,
      entityRef: r.entity_ref,
    }));
  }

  private summarize(products: ProductView[]): PortfolioView['summary'] {
    const active = products.filter((p) => !p.isDormant);
    const withBalance = active.filter((p) => p.totalBalance !== null);

    const totalBalance = withBalance.length
      ? withBalance.reduce((s, p) => s + (p.totalBalance ?? 0), 0)
      : null;

    // ממוצע משוקלל לפי צבירה — ממוצע פשוט היה נותן משקל זהה לקופה של
    // ₪800 ולקופה של ₪800,000, ומציג לסוכן תמונה מעוותת.
    const weighted = (pick: (p: ProductView) => number | null): number | null => {
      const usable = withBalance.filter((p) => pick(p) !== null);
      const base = usable.reduce((s, p) => s + (p.totalBalance ?? 0), 0);
      if (!usable.length || base === 0) return null;
      const sum = usable.reduce((s, p) => s + (pick(p) ?? 0) * (p.totalBalance ?? 0), 0);
      return Math.round((sum / base) * 1000) / 1000;
    };

    const coverageSum = (type: string): number | null => {
      const values = products
        .flatMap((p) => p.coverages)
        .filter((c) => c.coverageType === type)
        .map((c) => c.monthlyBenefit)
        .filter((v): v is number => v !== null);
      return values.length ? values.reduce((a, b) => a + b, 0) : null;
    };

    return {
      totalBalance,
      productsWithoutBalance: active.length - withBalance.length,
      feeOnDepositWeighted: weighted((p) => p.feeOnDepositPct),
      feeOnBalanceWeighted: weighted((p) => p.feeOnBalancePct),
      disabilityMonthly: coverageSum('disability'),
      survivorsMonthly: coverageSum('survivors'),
      dataCompleteness: products.length
        ? Math.round(
            (products.reduce((s, p) => s + p.dataCompleteness, 0) / products.length) * 1000,
          ) / 1000
        : null,
      productCount: products.length,
      dormantCount: products.filter((p) => p.isDormant).length,
    };
  }

  private advisories(products: ProductView[]): Advisory[] {
    const out: Advisory[] = [];
    const inTwelveMonths = new Date();
    inTwelveMonths.setMonth(inTwelveMonths.getMonth() + 12);

    for (const p of products) {
      const ref = p.policyNumber ? `policy:${p.policyNumber}` : null;

      if (p.hasGuaranteedAnnuityFactor) {
        out.push({
          ruleId: 'R-PEN-001',
          severity: 'critical',
          message:
            `ל${p.productTypeHe} ${p.policyNumber} יש מקדם קצבה מובטח` +
            (p.guaranteedFactorValue ? ` (${p.guaranteedFactorValue})` : '') +
            ' — ניוד יבטל אותו',
          entityRef: ref,
        });
      }

      if (p.feeAgreementEnd && new Date(p.feeAgreementEnd) <= inTwelveMonths) {
        out.push({
          ruleId: 'R-FEE-006',
          severity: 'warning',
          message:
            `הטבת דמי הניהול ב${p.productTypeHe} ${p.policyNumber} ` +
            `מסתיימת ב-${this.heDate(p.feeAgreementEnd)}`,
          entityRef: ref,
        });
      }

      if (p.productType === 'unknown') {
        out.push({
          ruleId: 'R-DAT-008',
          severity: 'warning',
          message: `סוג המוצר של ${p.policyNumber} לא זוהה — לא ניתן לכלול אותו בהמלצה`,
          entityRef: ref,
        });
      }

      if (p.totalBalance === null || p.feeOnBalancePct === null) {
        out.push({
          ruleId: 'R-DAT-008',
          severity: 'critical',
          message: `חסרים נתוני חובה ב${p.productTypeHe} ${p.policyNumber} — יחסום הפקת מסמך הנמקה`,
          entityRef: ref,
        });
      }

      if (p.beneficiaries.length === 0 && !p.isDormant) {
        out.push({
          ruleId: 'R-BEN-009',
          severity: 'info',
          message: `לא דווחו מוטבים ב${p.productTypeHe} ${p.policyNumber}`,
          entityRef: ref,
        });
      }
    }

    const order = { critical: 0, warning: 1, info: 2 } as const;
    return out.sort((a, b) => order[a.severity] - order[b.severity]);
  }

  /** תאריך בפורמט ישראלי. ISO בתוך טקסט עברי מתהפך בתצוגה. */
  private heDate(value: string | null): string {
    if (!value) return '—';
    const [y, m, d] = value.split('-');
    return `${d}/${m}/${y}`;
  }

  private latestReportDate(products: ProductView[]): string | null {
    const dates = products.map((p) => p.reportDate).filter((d): d is string => !!d);
    return dates.length ? dates.sort().at(-1)! : null;
  }

  private age(birthDate: string | Date | null): number | null {
    if (!birthDate) return null;
    const born = new Date(birthDate);
    const now = new Date();
    let years = now.getFullYear() - born.getFullYear();
    const md = now.getMonth() - born.getMonth();
    if (md < 0 || (md === 0 && now.getDate() < born.getDate())) years--;
    return years;
  }
}
