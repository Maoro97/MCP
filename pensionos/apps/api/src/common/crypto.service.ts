import { Injectable } from '@nestjs/common';
import {
  createCipheriv,
  createDecipheriv,
  createHmac,
  hkdfSync,
  randomBytes,
} from 'node:crypto';

/**
 * הצפנת שדות רגישים ו-HMAC לחיפוש.
 *
 * ⚠️ מימוש פיתוח. בייצור כל מפתח נגזר מ-KMS CMK נפרד לכל tenant, וחומר
 *    המפתח לעולם לא נמצא בזיכרון של האפליקציה (Data Keys בלבד). המבנה
 *    כאן זהה בכוונה — ההחלפה היא של מקור המפתח, לא של הקוראים.
 *
 * שני מפתחות נפרדים לכל tenant, נגזרים ב-HKDF:
 *   enc  — AES-256-GCM לת"ז ולשדות רגישים אחרים
 *   hmac — HMAC-SHA256 דטרמיניסטי, לחיפוש בלבד
 *
 * ההפרדה חשובה: מפתח החיפוש חייב להיות דטרמיניסטי (אחרת אין אינדקס),
 * ולכן הוא חלש יותר מהותית — אסור שישמש גם להצפנה.
 */
@Injectable()
export class CryptoService {
  private readonly master: Buffer;
  private readonly cache = new Map<string, { enc: Buffer; hmac: Buffer }>();

  constructor() {
    const hex = process.env.MASTER_KEY_HEX;
    if (!hex || hex.length !== 64) {
      throw new Error('MASTER_KEY_HEX must be 32 bytes in hex (64 chars)');
    }
    this.master = Buffer.from(hex, 'hex');
  }

  private keys(tenantId: string): { enc: Buffer; hmac: Buffer } {
    let entry = this.cache.get(tenantId);
    if (!entry) {
      entry = {
        enc: Buffer.from(
          hkdfSync('sha256', this.master, tenantId, 'pensionos:enc:v1', 32),
        ),
        hmac: Buffer.from(
          hkdfSync('sha256', this.master, tenantId, 'pensionos:hmac:v1', 32),
        ),
      };
      this.cache.set(tenantId, entry);
    }
    return entry;
  }

  /** ת"ז מנורמלת ל-9 ספרות — אחרת אותה ת"ז תיתן שני hash שונים. */
  normalizeNationalId(value: string): string {
    return value.replace(/\D/g, '').padStart(9, '0');
  }

  /** ולידציית ספרת ביקורת של ת"ז ישראלית. */
  isValidNationalId(value: string): boolean {
    const id = this.normalizeNationalId(value);
    if (id.length !== 9) return false;
    let total = 0;
    for (let i = 0; i < 9; i++) {
      const digit = Number(id[i]) * (i % 2 === 0 ? 1 : 2);
      total += digit < 10 ? digit : digit - 9;
    }
    return total % 10 === 0;
  }

  /** HMAC לחיפוש. per-tenant ⇒ אי אפשר להצליב לקוחות בין סוכנויות. */
  nationalIdHmac(tenantId: string, nationalId: string): Buffer {
    return createHmac('sha256', this.keys(tenantId).hmac)
      .update(this.normalizeNationalId(nationalId))
      .digest();
  }

  /** אותו HMAC כ-hex — הפורמט שמנוע הפענוח מצפה לו. */
  nationalIdHmacHex(tenantId: string, nationalId: string): string {
    return this.nationalIdHmac(tenantId, nationalId).toString('hex');
  }

  hmacKeyBase64(tenantId: string): string {
    return this.keys(tenantId).hmac.toString('base64');
  }

  /** AES-256-GCM. הפורמט: iv(12) ‖ tag(16) ‖ ciphertext */
  encrypt(tenantId: string, plaintext: string): Buffer {
    const iv = randomBytes(12);
    const cipher = createCipheriv('aes-256-gcm', this.keys(tenantId).enc, iv);
    const data = Buffer.concat([
      cipher.update(plaintext, 'utf8'),
      cipher.final(),
    ]);
    return Buffer.concat([iv, cipher.getAuthTag(), data]);
  }

  decrypt(tenantId: string, blob: Buffer): string {
    const iv = blob.subarray(0, 12);
    const tag = blob.subarray(12, 28);
    const decipher = createDecipheriv('aes-256-gcm', this.keys(tenantId).enc, iv);
    decipher.setAuthTag(tag);
    return Buffer.concat([
      decipher.update(blob.subarray(28)),
      decipher.final(),
    ]).toString('utf8');
  }
}
