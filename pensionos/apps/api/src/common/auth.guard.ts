import {
  CanActivate,
  ExecutionContext,
  Injectable,
  Logger,
  UnauthorizedException,
} from '@nestjs/common';
import { jwtVerify } from 'jose';

import type { Principal } from './principal';

/**
 * אימות JWT.
 *
 * `dev`  — טוקן HS256 שהונפק ע"י /v1/auth/dev-login. לפיתוח מקומי בלבד.
 * `oidc` — Cognito: אימות RS256 מול JWKS, בדיקת iss/aud/token_use, ואכיפת
 *          MFA (`amr` מכיל mfa). טרם מומש — ראה TODO למטה.
 *
 * ההפרדה מפורשת ולא "מצב ברירת מחדל": שרת שעולה עם AUTH_MODE=dev מחוץ
 * לפיתוח נופל בזמן עלייה, ולא מגלה זאת בייצור.
 */
@Injectable()
export class AuthGuard implements CanActivate {
  private readonly logger = new Logger(AuthGuard.name);
  private readonly mode = process.env.AUTH_MODE ?? 'oidc';
  private readonly secret = new TextEncoder().encode(process.env.JWT_SECRET ?? '');

  constructor() {
    if (this.mode === 'dev' && process.env.NODE_ENV === 'production') {
      throw new Error(
        'AUTH_MODE=dev is forbidden in production — refusing to start',
      );
    }
    if (this.mode === 'oidc') {
      throw new Error(
        'AUTH_MODE=oidc is not implemented yet (Cognito JWKS verification pending)',
      );
    }
  }

  async canActivate(ctx: ExecutionContext): Promise<boolean> {
    const request = ctx.switchToHttp().getRequest();
    const header: string | undefined = request.headers?.authorization;

    if (!header?.startsWith('Bearer ')) {
      throw new UnauthorizedException('missing bearer token');
    }

    try {
      const { payload } = await jwtVerify(header.slice(7), this.secret, {
        issuer: 'pensionos-dev',
      });

      const principal: Principal = {
        userId: String(payload.sub),
        tenantId: String(payload.tenant_id),
        role: payload.role as Principal['role'],
        email: String(payload.email ?? ''),
      };

      if (!principal.userId || !principal.tenantId || !principal.role) {
        throw new UnauthorizedException('token missing required claims');
      }

      request.principal = principal;
      return true;
    } catch (err) {
      // לא מחזירים את סיבת הכשל ללקוח — היא עוזרת לתוקף יותר מאשר למשתמש
      this.logger.warn(`token rejected: ${(err as Error).message}`);
      throw new UnauthorizedException('invalid token');
    }
  }
}
