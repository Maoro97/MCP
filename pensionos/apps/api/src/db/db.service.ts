import {
  Injectable,
  Logger,
  OnApplicationShutdown,
  OnModuleInit,
} from '@nestjs/common';
import postgres, { type Sql } from 'postgres';

import type { Principal } from '../common/principal';

export type Tx = Sql<{}>;

/**
 * גישה למסד הנתונים.
 *
 * הכלל היחיד שאסור לשבור: **אין שאילתה על נתוני לקוח מחוץ ל-`withTenant`**.
 * הפונקציה פותחת טרנזקציה, מזריקה את הקשר ה-RLS, ורק אז מריצה את הקוד.
 * ה-pool הוא per-transaction, כך שההקשר לא יכול לדלוף בין בקשות.
 */
@Injectable()
export class DbService implements OnModuleInit, OnApplicationShutdown {
  private readonly logger = new Logger(DbService.name);
  private readonly sql: Sql;

  constructor() {
    const url = process.env.DATABASE_URL;
    if (!url) throw new Error('DATABASE_URL is required');

    this.sql = postgres(url, {
      max: Number(process.env.DB_POOL_MAX ?? 10),
      idle_timeout: 30,
      connect_timeout: 10,
      prepare: false, // תואם ל-pgBouncer ב-transaction mode
      onnotice: () => {},
    });
  }

  async onModuleInit(): Promise<void> {
    await this.assertNotPrivileged();
  }

  /**
   * בדיקת עלייה חוסמת: חיבור כ-superuser או עם BYPASSRLS מבטל את בידוד
   * ה-Tenant לחלוטין — וגרוע מכך, כל הבדיקות ימשיכו לעבור. עדיף ששרת
   * מוגדר לא נכון לא יעלה בכלל.
   */
  private async assertNotPrivileged(): Promise<void> {
    const [row] = await this.sql<
      { is_superuser: string; bypassrls: boolean; who: string }[]
    >`
      SELECT current_setting('is_superuser') AS is_superuser,
             rolbypassrls                    AS bypassrls,
             current_user                    AS who
      FROM pg_roles WHERE rolname = current_user
    `;

    if (!row) throw new Error('could not determine database role');

    if (row.is_superuser === 'on' || row.bypassrls) {
      throw new Error(
        `database role "${row.who}" is superuser or has BYPASSRLS — ` +
          'tenant isolation would be silently disabled. Refusing to start.',
      );
    }
    this.logger.log(`connected as "${row.who}" (RLS enforced)`);
  }

  /** מריץ פעולה בהקשר Tenant. זו הדרך היחידה לגעת בנתוני לקוחות. */
  async withTenant<T>(
    principal: Principal,
    fn: (tx: Tx) => Promise<T>,
  ): Promise<T> {
    return this.sql.begin(async (tx) => {
      await tx`
        SELECT set_config('app.current_tenant', ${principal.tenantId}, true),
               set_config('app.current_user',   ${principal.userId},   true),
               set_config('app.current_role',   ${principal.role},     true)
      `;
      return fn(tx as unknown as Tx);
    }) as Promise<T>;
  }

  /** גישה ללא הקשר Tenant — מותרת רק לטבלאות ייחוס גלובליות. */
  get reference(): Sql {
    return this.sql;
  }

  async onApplicationShutdown(): Promise<void> {
    await this.sql.end({ timeout: 5 });
  }
}
