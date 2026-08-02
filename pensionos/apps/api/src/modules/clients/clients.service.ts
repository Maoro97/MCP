import {
  BadRequestException,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import { z } from 'zod';

import { AuditService } from '../../common/audit.service';
import { CryptoService } from '../../common/crypto.service';
import type { Principal } from '../../common/principal';
import { DbService } from '../../db/db.service';

export const CreateClientSchema = z.object({
  nationalId: z.string().min(5).max(12),
  firstName: z.string().min(1).max(80),
  lastName: z.string().min(1).max(80),
  birthDate: z.string().date().optional(),
  phoneE164: z
    .string()
    .regex(/^\+972\d{8,9}$/, 'נדרש מספר ישראלי בפורמט E.164')
    .optional(),
  email: z.string().email().optional(),
  maritalStatus: z.string().max(30).optional(),
});
export type CreateClientDto = z.infer<typeof CreateClientSchema>;

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

function age(birthDate: string | Date | null): number | null {
  if (!birthDate) return null;
  const born = new Date(birthDate);
  const now = new Date();
  let years = now.getFullYear() - born.getFullYear();
  const monthDelta = now.getMonth() - born.getMonth();
  if (monthDelta < 0 || (monthDelta === 0 && now.getDate() < born.getDate())) {
    years--;
  }
  return years;
}

@Injectable()
export class ClientsService {
  constructor(
    private readonly db: DbService,
    private readonly crypto: CryptoService,
    private readonly audit: AuditService,
  ) {}

  async create(principal: Principal, dto: CreateClientDto): Promise<{ id: string }> {
    if (!this.crypto.isValidNationalId(dto.nationalId)) {
      throw new BadRequestException('תעודת הזהות אינה תקינה (ספרת ביקורת)');
    }
    const normalized = this.crypto.normalizeNationalId(dto.nationalId);

    return this.db.withTenant(principal, async (tx) => {
      const hash = this.crypto.nationalIdHmac(principal.tenantId, normalized);

      // זיהוי כפילות לפני יצירה. שים לב: RLS מגביל את החיפוש ל-tenant,
      // אבל לא להיקף הסוכן — כדי שנוכל לומר "הלקוח מטופל ע"י סוכן אחר"
      // בלי לחשוף את פרטיו.
      const existing = await tx<{ id: string; owner_user_id: string | null }[]>`
        SELECT id, owner_user_id FROM clients.clients
        WHERE national_id_hash = ${hash} AND deleted_at IS NULL
      `;
      if (existing.length > 0) {
        throw new BadRequestException('לקוח עם תעודת זהות זו כבר קיים בסוכנות');
      }

      const [row] = await tx<{ id: string }[]>`
        INSERT INTO clients.clients
          (tenant_id, owner_user_id, national_id_enc, national_id_hash,
           national_id_last4, first_name, last_name, birth_date, phone_e164,
           email, marital_status)
        VALUES
          (${principal.tenantId}, ${principal.userId},
           ${this.crypto.encrypt(principal.tenantId, normalized)}, ${hash},
           ${normalized.slice(-4)}, ${dto.firstName}, ${dto.lastName},
           ${dto.birthDate ?? null}, ${dto.phoneE164 ?? null},
           ${dto.email ?? null}, ${dto.maritalStatus ?? null})
        RETURNING id
      `;
      if (!row) throw new Error('insert returned no row');

      await this.audit.record(tx, principal, {
        action: 'CREATE',
        entityType: 'client',
        entityId: row.id,
        clientId: row.id,
        after: { firstName: dto.firstName, lastName: dto.lastName },
      });

      return { id: row.id };
    });
  }

  async list(principal: Principal, search?: string): Promise<ClientSummary[]> {
    return this.db.withTenant(principal, async (tx) => {
      const pattern = search ? `%${search}%` : null;
      const rows = await tx<any[]>`
        SELECT c.id, c.first_name, c.last_name, c.national_id_last4,
               c.birth_date, c.phone_e164,
               COUNT(p.id)::int                       AS product_count,
               NULLIF(SUM(b.total_balance), 0)::float AS total_balance,
               MAX(f.received_at)                     AS last_ingest_at
        FROM clients.clients c
        LEFT JOIN portfolio.products p
               ON p.client_id = c.id AND p.status <> 'closed'
        LEFT JOIN portfolio.product_balances b
               ON b.product_id = p.id AND b.as_of_date = p.report_date
        LEFT JOIN clearing.files f ON f.id = p.source_file_id
        WHERE c.deleted_at IS NULL
          AND (${pattern}::text IS NULL
               OR c.first_name || ' ' || c.last_name ILIKE ${pattern}
               OR c.national_id_last4 = ${search ?? null})
        GROUP BY c.id
        ORDER BY c.last_name, c.first_name
        LIMIT 200
      `;

      await this.audit.record(tx, principal, {
        action: 'READ',
        entityType: 'client_list',
        after: { count: rows.length, search: search ?? null },
      });

      return rows.map((r) => ({
        id: r.id,
        firstName: r.first_name,
        lastName: r.last_name,
        nationalIdLast4: r.national_id_last4,
        birthDate: r.birth_date ? new Date(r.birth_date).toISOString().slice(0, 10) : null,
        age: age(r.birth_date),
        phoneE164: r.phone_e164,
        productCount: r.product_count,
        totalBalance: r.total_balance,
        lastIngestAt: r.last_ingest_at ? new Date(r.last_ingest_at).toISOString() : null,
      }));
    });
  }

  /** טוען לקוח, או זורק 404. גישה חוצת-tenant תיראה כאן כ"לא נמצא". */
  async requireClient(
    tx: any,
    clientId: string,
  ): Promise<{ id: string; national_id_hash: Buffer; first_name: string; last_name: string }> {
    const [row] = await tx`
      SELECT id, national_id_hash, first_name, last_name
      FROM clients.clients
      WHERE id = ${clientId} AND deleted_at IS NULL
    `;
    if (!row) throw new NotFoundException('לקוח לא נמצא');
    return row;
  }
}
