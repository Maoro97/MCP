import { Injectable, Logger } from '@nestjs/common';
import { createHash } from 'node:crypto';

import { AuditService } from '../../common/audit.service';
import { CryptoService } from '../../common/crypto.service';
import type { Principal } from '../../common/principal';
import { DbService, type Tx } from '../../db/db.service';
import { ClientsService } from '../clients/clients.service';
import type { ParsedProduct, ParseResult } from './parser.client';
import { ParserClient } from './parser.client';

export interface IngestSummary {
  fileId: string;
  parseJobId: string;
  status: ParseResult['status'];
  productsPersisted: number;
  /** מוצרים שהתעלמנו מהם כי הדיווח הקיים עדכני או שלם יותר. */
  staleSkipped: number;
  duplicate: boolean;
  issues: { info: number; warning: number; error: number; blocker: number };
  blockingIssues: string[];
  durationMs: number;
}

@Injectable()
export class IngestionService {
  private readonly logger = new Logger(IngestionService.name);

  constructor(
    private readonly db: DbService,
    private readonly parser: ParserClient,
    private readonly crypto: CryptoService,
    private readonly clients: ClientsService,
    private readonly audit: AuditService,
  ) {}

  async ingest(
    principal: Principal,
    clientId: string,
    file: { buffer: Buffer; originalname: string },
  ): Promise<IngestSummary> {
    const sha256 = createHash('sha256').update(file.buffer).digest();

    // שלב 1 — קריאה + פענוח מחוץ לטרנזקציה. פענוח יכול לקחת עשרות שניות,
    // ואסור להחזיק טרנזקציה פתוחה כל אותו זמן.
    const { expectedHash, hmacKey } = await this.db.withTenant(
      principal,
      async (tx) => {
        const client = await this.clients.requireClient(tx, clientId);
        return {
          expectedHash: Buffer.from(client.national_id_hash).toString('hex'),
          hmacKey: this.crypto.hmacKeyBase64(principal.tenantId),
        };
      },
    );

    const result = await this.parser.parse(file, {
      expectedNationalIdHash: expectedHash,
      hmacKeyB64: hmacKey,
    });

    // שלב 2 — התמדה, הכל בטרנזקציה אחת
    return this.db.withTenant(principal, async (tx) => {
      const duplicate = await this.isDuplicate(tx, principal.tenantId, sha256);
      if (duplicate) {
        // אותו קובץ בדיוק כבר נקלט. לא מפענחים שוב ולא כותבים שוב —
        // אבל כן מדווחים, כדי שהסוכן יבין למה "לא קרה כלום".
        const [existing] = await tx<{ id: string }[]>`
          SELECT id FROM clearing.files WHERE sha256 = ${sha256}
        `;
        return {
          fileId: existing!.id,
          parseJobId: '',
          status: result.status,
          productsPersisted: 0,
          staleSkipped: 0,
          duplicate: true,
          issues: this.countIssues(result),
          blockingIssues: [],
          durationMs: result.stats.duration_ms,
        };
      }

      const fileId = await this.insertFile(tx, principal, clientId, {
        sha256,
        file,
        result,
      });
      const parseJobId = await this.insertParseJob(tx, principal, fileId, result);
      await this.insertIssues(tx, principal, parseJobId, result);

      // תוצאה בהסגר לעולם לא נכנסת לשכבה הקנונית. הקובץ נשמר, החריגים
      // נשמרים — אבל הנתונים עצמם לא נוגעים בתיק הלקוח.
      let persisted = 0;
      let staleSkipped = 0;
      if (result.status === 'succeeded' || result.status === 'partial') {
        for (const product of result.products) {
          const applied = await this.upsertProduct(
            tx,
            principal,
            clientId,
            fileId,
            product,
          );
          if (applied) persisted++;
          else staleSkipped++;
        }
      }

      await this.audit.record(tx, principal, {
        action: 'INGEST',
        entityType: 'clearing_file',
        entityId: fileId,
        clientId,
        after: {
          status: result.status,
          products: persisted,
          fixes: result.sanitize_report.fixes,
        },
      });

      return {
        fileId,
        parseJobId,
        status: result.status,
        productsPersisted: persisted,
        staleSkipped,
        duplicate: false,
        issues: this.countIssues(result),
        blockingIssues: result.issues
          .filter((i) => i.severity === 'blocker' || i.severity === 'error')
          .map((i) => i.message_he),
        durationMs: result.stats.duration_ms,
      };
    });
  }

  // ------------------------------------------------------------------

  private countIssues(result: ParseResult) {
    return result.issues.reduce(
      (acc, i) => ({ ...acc, [i.severity]: acc[i.severity] + 1 }),
      { info: 0, warning: 0, error: 0, blocker: 0 },
    );
  }

  private async isDuplicate(tx: Tx, tenantId: string, sha256: Buffer) {
    const rows = await tx<{ id: string }[]>`
      SELECT id FROM clearing.files
      WHERE tenant_id = ${tenantId} AND sha256 = ${sha256}
    `;
    return rows.length > 0;
  }

  private async insertFile(
    tx: Tx,
    principal: Principal,
    clientId: string,
    ctx: { sha256: Buffer; file: { buffer: Buffer; originalname: string }; result: ParseResult },
  ): Promise<string> {
    const { result } = ctx;
    await this.ensureProvider(tx, result);

    const [row] = await tx<{ id: string }[]>`
      INSERT INTO clearing.files
        (tenant_id, request_id, client_id, source, provider_code, s3_bucket,
         s3_key, original_name, size_bytes, sha256, declared_encoding,
         detected_encoding, standard_version, status)
      VALUES
        (${principal.tenantId}, NULL, ${clientId}, 'manual_upload',
         ${result.provider_code}, ${process.env.RAW_BUCKET ?? 'local-dev'},
         ${`manual/${principal.tenantId}/${ctx.sha256.toString('hex')}.xml`},
         ${ctx.file.originalname}, ${ctx.file.buffer.length}, ${ctx.sha256},
         ${result.sanitize_report.declared_encoding},
         ${result.sanitize_report.detected_encoding},
         ${result.standard_version},
         ${this.fileStatus(result.status)})
      RETURNING id
    `;
    return row!.id;
  }

  private fileStatus(status: ParseResult['status']) {
    switch (status) {
      case 'succeeded':
      case 'partial':
        return 'parsed';
      case 'no_data':
        return 'no_data';
      case 'quarantined':
        return 'quarantined';
      default:
        return 'failed';
    }
  }

  /** יצרן שטרם מוכר נרשם אוטומטית — עדיף מלהפיל קליטה על FK. */
  private async ensureProvider(tx: Tx, result: ParseResult): Promise<void> {
    const codes = new Map<string, string>();
    if (result.provider_code) {
      codes.set(result.provider_code, result.products[0]?.provider_name ?? result.provider_code);
    }
    for (const p of result.products) {
      if (p.provider_code) codes.set(p.provider_code, p.provider_name ?? p.provider_code);
    }
    for (const [code, name] of codes) {
      await tx`
        INSERT INTO clearing.providers (code, name_he, provider_type)
        VALUES (${code}, ${name}, 'investment_house')
        ON CONFLICT (code) DO NOTHING
      `;
    }
  }

  private async insertParseJob(
    tx: Tx,
    principal: Principal,
    fileId: string,
    result: ParseResult,
  ): Promise<string> {
    const [row] = await tx<{ id: string }[]>`
      INSERT INTO clearing.parse_jobs
        (tenant_id, file_id, status, parser_version, mapping_version,
         sanitize_report, stats, started_at, finished_at, duration_ms)
      VALUES
        (${principal.tenantId}, ${fileId}, ${result.status},
         ${result.parser_version}, ${result.mapping_version},
         ${JSON.stringify(result.sanitize_report)}::jsonb,
         ${JSON.stringify(result.stats)}::jsonb,
         now(), now(), ${result.stats.duration_ms})
      RETURNING id
    `;
    return row!.id;
  }

  private async insertIssues(
    tx: Tx,
    principal: Principal,
    parseJobId: string,
    result: ParseResult,
  ): Promise<void> {
    for (const issue of result.issues) {
      await tx`
        INSERT INTO clearing.parse_issues
          (tenant_id, parse_job_id, severity, code, canonical_field, xpath,
           raw_value, message_he, entity_ref, context)
        VALUES
          (${principal.tenantId}, ${parseJobId}, ${issue.severity}, ${issue.code},
           ${issue.canonical_field}, ${issue.xpath}, ${issue.raw_value},
           ${issue.message_he}, ${issue.entity_ref},
           ${JSON.stringify(issue.context ?? {})}::jsonb)
      `;
    }
  }

  /**
   * שומר מוצר, אלא אם הדיווח הקיים עדיף.
   *
   * זהו כלל ה-Reconcile של המפרט, שחייב לחול גם **בין קבצים** ולא רק
   * בתוך קובץ בודד: קופה מדווחת ע"י יותר מיצרן אחד ובקבצים שהגיעו
   * בזמנים שונים. בלי הבדיקה הזו, קובץ ישן או חלקי שנקלט אחרון מוחק
   * נתונים תקינים — בשקט, בלי שגיאה, ובלי שאיש ישים לב.
   *
   * סדר העדיפות: תאריך נכונות עדכני יותר מנצח; בתיקו — הרשומה השלמה
   * יותר. דיווח ללא תאריך נחשב לישן ביותר.
   *
   * @returns האם הדיווח נקלט (false = הדיווח הקיים עדיף)
   */
  private async upsertProduct(
    tx: Tx,
    principal: Principal,
    clientId: string,
    fileId: string,
    p: ParsedProduct,
  ): Promise<boolean> {
    const [row] = await tx<{ id: string }[]>`
      INSERT INTO portfolio.products AS existing
        (tenant_id, client_id, provider_code, source_file_id, product_type,
         policy_number, product_name, employer_name, join_date, status,
         is_dormant, has_guaranteed_annuity_factor, guaranteed_factor_value,
         is_pre_2013, track_code, track_name, report_date, data_completeness,
         provenance, raw)
      VALUES
        (${principal.tenantId}, ${clientId}, ${p.provider_code}, ${fileId},
         ${p.product_type}, ${p.policy_number}, ${p.product_name},
         ${p.employer_name}, ${p.join_date}, ${p.status}, ${p.is_dormant},
         ${p.has_guaranteed_annuity_factor}, ${p.guaranteed_factor_value},
         ${p.is_pre_2013}, ${p.track_code}, ${p.track_name}, ${p.report_date},
         ${p.data_completeness}, ${JSON.stringify(p.provenance)}::jsonb,
         ${JSON.stringify(p.raw)}::jsonb)
      ON CONFLICT (tenant_id, client_id, provider_code, policy_number, product_type)
      DO UPDATE SET
        source_file_id = EXCLUDED.source_file_id,
        product_name   = EXCLUDED.product_name,
        employer_name  = EXCLUDED.employer_name,
        join_date      = EXCLUDED.join_date,
        status         = EXCLUDED.status,
        is_dormant     = EXCLUDED.is_dormant,
        has_guaranteed_annuity_factor = EXCLUDED.has_guaranteed_annuity_factor,
        guaranteed_factor_value       = EXCLUDED.guaranteed_factor_value,
        is_pre_2013    = EXCLUDED.is_pre_2013,
        track_code     = EXCLUDED.track_code,
        track_name     = EXCLUDED.track_name,
        report_date    = EXCLUDED.report_date,
        data_completeness = EXCLUDED.data_completeness,
        provenance     = EXCLUDED.provenance,
        raw            = EXCLUDED.raw,
        updated_at     = now()
      WHERE
        COALESCE(EXCLUDED.report_date, '-infinity'::date)
          > COALESCE(existing.report_date, '-infinity'::date)
        OR (
          COALESCE(EXCLUDED.report_date, '-infinity'::date)
            = COALESCE(existing.report_date, '-infinity'::date)
          AND EXCLUDED.data_completeness >= existing.data_completeness
        )
      RETURNING id
    `;

    // ה-WHERE לא התקיים ⇒ הדיווח הקיים עדיף. לא נוגעים גם בישויות הבן,
    // אחרת היינו מחליפים כיסויים תקינים בכיסויים מדיווח ישן יותר.
    if (!row) return false;

    const productId = row.id;

    // as_of_date נגזר מתאריך הנכונות; אם היצרן לא דיווח — היום, כדי שתהיה
    // שורת יתרה אחת ויחידה. החוסר עצמו כבר מסומן כחריג.
    const asOf = p.report_date ?? new Date().toISOString().slice(0, 10);

    await tx`
      INSERT INTO portfolio.product_balances
        (tenant_id, product_id, as_of_date, total_balance, employee_component,
         employer_component, severance_component, ytd_yield_pct)
      VALUES
        (${principal.tenantId}, ${productId}, ${asOf}, ${p.total_balance},
         ${p.employee_component}, ${p.employer_component},
         ${p.severance_component}, ${p.ytd_yield_pct})
      ON CONFLICT (product_id, as_of_date) DO UPDATE SET
        total_balance       = EXCLUDED.total_balance,
        employee_component  = EXCLUDED.employee_component,
        employer_component  = EXCLUDED.employer_component,
        severance_component = EXCLUDED.severance_component,
        ytd_yield_pct       = EXCLUDED.ytd_yield_pct
    `;

    await tx`
      INSERT INTO portfolio.product_fees
        (tenant_id, product_id, as_of_date, fee_on_deposit_pct,
         fee_on_balance_pct, fee_agreement_end)
      VALUES
        (${principal.tenantId}, ${productId}, ${asOf}, ${p.fee_on_deposit_pct},
         ${p.fee_on_balance_pct}, ${p.fee_agreement_end})
      ON CONFLICT (product_id, as_of_date) DO UPDATE SET
        fee_on_deposit_pct = EXCLUDED.fee_on_deposit_pct,
        fee_on_balance_pct = EXCLUDED.fee_on_balance_pct,
        fee_agreement_end  = EXCLUDED.fee_agreement_end
    `;

    // כיסויים ומוטבים מוחלפים במלואם: הם תמונת מצב של הדיווח האחרון,
    // ומיזוג חלקי היה יוצר "כיסוי רפאים" שכבר בוטל.
    await tx`DELETE FROM portfolio.coverages WHERE product_id = ${productId}`;
    for (const c of p.coverages) {
      await tx`
        INSERT INTO portfolio.coverages
          (tenant_id, product_id, coverage_type, coverage_name, sum_insured,
           monthly_benefit, cost_monthly, waiting_period_m, is_active)
        VALUES
          (${principal.tenantId}, ${productId}, ${c.coverage_type ?? 'other'},
           ${c.coverage_name}, ${c.sum_insured}, ${c.monthly_benefit},
           ${c.cost_monthly}, ${c.waiting_period_m}, ${c.is_active})
      `;
    }

    await tx`DELETE FROM portfolio.beneficiaries WHERE product_id = ${productId}`;
    for (const b of p.beneficiaries) {
      await tx`
        INSERT INTO portfolio.beneficiaries
          (tenant_id, product_id, full_name, relation, share_pct, updated_on)
        VALUES
          (${principal.tenantId}, ${productId}, ${b.full_name}, ${b.relation},
           ${b.share_pct}, ${b.updated_on})
      `;
    }

    return true;
  }
}
