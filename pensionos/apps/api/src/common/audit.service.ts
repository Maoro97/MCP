import { Injectable } from '@nestjs/common';

import type { Tx } from '../db/db.service';
import type { Principal } from './principal';

export interface AuditEntry {
  action: 'READ' | 'CREATE' | 'UPDATE' | 'EXPORT' | 'SIGN' | 'LOGIN' | 'INGEST';
  entityType: string;
  entityId?: string | null;
  clientId?: string | null;
  before?: unknown;
  after?: unknown;
  ip?: string | null;
  userAgent?: string | null;
  requestId?: string | null;
}

/**
 * יומן ביקורת.
 *
 * שתי נקודות שקל לפספס ושהן דרישה מפורשת בתקנות הגנת הפרטיות:
 *  1. גם **קריאה** נרשמת, לא רק שינוי. "מי צפה בתיק של הלקוח" היא בדיוק
 *     השאלה שנשאלת בביקורת.
 *  2. הרישום מתבצע **בתוך אותה טרנזקציה** של הפעולה עצמה. אחרת פעולה
 *     שנכשלה ברולבק תשאיר רישום שקרי, או להפך.
 */
@Injectable()
export class AuditService {
  async record(tx: Tx, principal: Principal, entry: AuditEntry): Promise<void> {
    await tx`
      INSERT INTO audit.logs
        (tenant_id, actor_user_id, actor_type, action, entity_type, entity_id,
         client_id, ip_address, user_agent, request_id, before, after)
      VALUES
        (${principal.tenantId}, ${principal.userId}, 'user', ${entry.action},
         ${entry.entityType}, ${entry.entityId ?? null}, ${entry.clientId ?? null},
         ${entry.ip ?? null}, ${entry.userAgent ?? null}, ${entry.requestId ?? null},
         ${entry.before ? JSON.stringify(entry.before) : null}::jsonb,
         ${entry.after ? JSON.stringify(entry.after) : null}::jsonb)
    `;
  }
}
