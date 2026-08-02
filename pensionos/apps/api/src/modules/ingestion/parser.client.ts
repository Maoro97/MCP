import {
  Injectable,
  Logger,
  ServiceUnavailableException,
} from '@nestjs/common';

/** חוזה הפלט של מנוע הפענוח (services/parser). snake_case כפי שהוא. */
export interface ParsedCoverage {
  coverage_type: string | null;
  coverage_name: string | null;
  sum_insured: number | null;
  monthly_benefit: number | null;
  cost_monthly: number | null;
  waiting_period_m: number | null;
  is_active: boolean;
}

export interface ParsedBeneficiary {
  full_name: string | null;
  relation: string | null;
  share_pct: number | null;
  updated_on: string | null;
}

export interface ParsedProduct {
  provider_code: string | null;
  provider_name: string | null;
  policy_number: string | null;
  product_type: string;
  product_name: string | null;
  employer_name: string | null;
  join_date: string | null;
  status: string;
  is_dormant: boolean;
  report_date: string | null;
  total_balance: number | null;
  employee_component: number | null;
  employer_component: number | null;
  severance_component: number | null;
  ytd_yield_pct: number | null;
  fee_on_deposit_pct: number | null;
  fee_on_balance_pct: number | null;
  fee_agreement_end: string | null;
  track_code: string | null;
  track_name: string | null;
  has_guaranteed_annuity_factor: boolean | null;
  guaranteed_factor_value: number | null;
  is_pre_2013: boolean | null;
  data_completeness: number;
  coverages: ParsedCoverage[];
  beneficiaries: ParsedBeneficiary[];
  provenance: Record<string, { xpath: string; raw: string | null; confidence: number; fixes: string[] }>;
  raw: Record<string, unknown>;
}

export interface ParseIssue {
  severity: 'info' | 'warning' | 'error' | 'blocker';
  code: string;
  message_he: string;
  canonical_field: string | null;
  xpath: string | null;
  raw_value: string | null;
  entity_ref: string | null;
  context: Record<string, unknown>;
}

export interface ParseResult {
  status: 'succeeded' | 'partial' | 'no_data' | 'failed' | 'quarantined';
  parser_version: string;
  mapping_version: string | null;
  standard_version: string | null;
  file_id: string | null;
  sanitize_report: {
    declared_encoding: string | null;
    detected_encoding: string | null;
    fixes: string[];
    bytes_in: number;
    chars_out: number;
  };
  subject: {
    national_id: string | null;
    first_name: string | null;
    last_name: string | null;
    birth_date: string | null;
  } | null;
  provider_code: string | null;
  products: ParsedProduct[];
  issues: ParseIssue[];
  stats: {
    products: number;
    coverages: number;
    beneficiaries: number;
    duplicates_merged: number;
    duration_ms: number;
  };
}

/**
 * לקוח HTTP למנוע הפענוח.
 *
 * הגבול בין TypeScript ל-Python עובר כאן ורק כאן: endpoint אחד, חוזה JSON
 * אחד, אפס לוגיקה עסקית מעבר לגבול.
 */
@Injectable()
export class ParserClient {
  private readonly logger = new Logger(ParserClient.name);
  private readonly baseUrl = process.env.PARSER_URL ?? 'http://localhost:8081';
  private readonly token = process.env.PARSER_INTERNAL_TOKEN ?? '';
  private readonly timeoutMs = Number(process.env.PARSER_TIMEOUT_MS ?? 120_000);

  async parse(
    file: { buffer: Buffer; originalname: string },
    opts: { expectedNationalIdHash: string; hmacKeyB64: string },
  ): Promise<ParseResult> {
    const form = new FormData();
    form.append(
      'file',
      new Blob([new Uint8Array(file.buffer)]),
      file.originalname,
    );

    const url = new URL('/internal/parse', this.baseUrl);
    url.searchParams.set('file_id', file.originalname);
    url.searchParams.set('expected_national_id_hash', opts.expectedNationalIdHash);
    url.searchParams.set('hmac_key_b64', opts.hmacKeyB64);

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const res = await fetch(url, {
        method: 'POST',
        body: form,
        signal: controller.signal,
        headers: this.token ? { 'x-internal-token': this.token } : undefined,
      });

      if (!res.ok) {
        const detail = await res.text().catch(() => '');
        throw new ServiceUnavailableException(
          `parser returned ${res.status}: ${detail.slice(0, 200)}`,
        );
      }
      return (await res.json()) as ParseResult;
    } catch (err) {
      if (err instanceof ServiceUnavailableException) throw err;
      this.logger.error(`parser unreachable: ${(err as Error).message}`);
      throw new ServiceUnavailableException('מנוע הפענוח אינו זמין כרגע');
    } finally {
      clearTimeout(timer);
    }
  }

  async health(): Promise<boolean> {
    try {
      const res = await fetch(new URL('/internal/health', this.baseUrl), {
        signal: AbortSignal.timeout(3000),
      });
      return res.ok;
    } catch {
      return false;
    }
  }
}
