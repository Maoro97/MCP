import { createParamDecorator, type ExecutionContext } from '@nestjs/common';

/**
 * זהות המבצע, כפי שנגזרה מה-JWT. זהו המקור היחיד להקשר ה-RLS —
 * שום ערך כאן לא מגיע מגוף הבקשה או מ-query string.
 */
export interface Principal {
  userId: string;
  tenantId: string;
  role: 'agent' | 'agency_admin' | 'compliance' | 'support';
  email: string;
}

export const CurrentUser = createParamDecorator(
  (_data: unknown, ctx: ExecutionContext): Principal => {
    const request = ctx.switchToHttp().getRequest();
    if (!request.principal) {
      // אם הגענו לכאן, ה-Guard לא רץ — כשל תצורה, לא כשל הרשאה
      throw new Error('principal missing: route is not behind AuthGuard');
    }
    return request.principal as Principal;
  },
);
