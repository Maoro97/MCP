import { Body, Controller, ForbiddenException, Post } from '@nestjs/common';
import { SignJWT } from 'jose';
import { z } from 'zod';

const DevLoginSchema = z.object({
  userId: z.string().uuid(),
  tenantId: z.string().uuid(),
  role: z.enum(['agent', 'agency_admin', 'compliance', 'support']),
  email: z.string().email().optional(),
});

/**
 * הנפקת טוקן לפיתוח מקומי בלבד.
 *
 * בייצור אין endpoint כזה: Cognito מנפיק את הטוקן, ו-`tenant_id`/`role`
 * מגיעים מ-custom attributes של ה-User Pool. במכוון אין כאן חיפוש
 * במסד הנתונים — טבלת המשתמשים מוגנת ב-RLS, ולוּ הוספנו מסלול לעקוף
 * אותה לצורך התחברות, היינו פותחים בדיוק את החור שה-RLS נועד לסתום.
 */
@Controller('v1/auth')
export class AuthController {
  @Post('dev-login')
  async devLogin(@Body() body: unknown) {
    if (process.env.AUTH_MODE !== 'dev') {
      throw new ForbiddenException('dev-login is disabled');
    }
    const dto = DevLoginSchema.parse(body);
    const secret = new TextEncoder().encode(process.env.JWT_SECRET ?? '');

    const token = await new SignJWT({
      tenant_id: dto.tenantId,
      role: dto.role,
      email: dto.email ?? 'dev@pensionos.local',
    })
      .setProtectedHeader({ alg: 'HS256' })
      .setSubject(dto.userId)
      .setIssuer('pensionos-dev')
      .setIssuedAt()
      .setExpirationTime('8h')
      .sign(secret);

    return { accessToken: token, expiresIn: 8 * 3600 };
  }
}
