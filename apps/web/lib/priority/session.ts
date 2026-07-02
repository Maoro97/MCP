import "server-only";
import { cookies } from "next/headers";
import {
  createCipheriv,
  createDecipheriv,
  createHash,
  randomBytes,
} from "crypto";

/*
 * Server-side session handling. OAuth tokens live ONLY in an httpOnly, encrypted
 * cookie — they are never exposed to browser JavaScript. AES-256-GCM with a key
 * derived from SESSION_SECRET.
 */

const SESSION_COOKIE = "pc_session";
const OAUTH_COOKIE = "pc_oauth";

export interface SessionData {
  accessToken: string;
  refreshToken?: string;
  /** Epoch ms when the access token expires. */
  expiresAt?: number;
  sub?: string;
  name?: string;
}

/** Short-lived state carried between /login and /callback. */
export interface OAuthState {
  verifier: string;
  state: string;
}

function key(secret: string): Buffer {
  return createHash("sha256").update(secret).digest();
}

function encrypt(secret: string, payload: unknown): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key(secret), iv);
  const data = Buffer.concat([
    cipher.update(JSON.stringify(payload), "utf8"),
    cipher.final(),
  ]);
  const tag = cipher.getAuthTag();
  return [
    iv.toString("base64url"),
    tag.toString("base64url"),
    data.toString("base64url"),
  ].join(".");
}

function decrypt<T>(secret: string, token: string): T | null {
  try {
    const [ivB64, tagB64, dataB64] = token.split(".");
    if (!ivB64 || !tagB64 || !dataB64) return null;
    const decipher = createDecipheriv(
      "aes-256-gcm",
      key(secret),
      Buffer.from(ivB64, "base64url")
    );
    decipher.setAuthTag(Buffer.from(tagB64, "base64url"));
    const out = Buffer.concat([
      decipher.update(Buffer.from(dataB64, "base64url")),
      decipher.final(),
    ]);
    return JSON.parse(out.toString("utf8")) as T;
  } catch {
    return null;
  }
}

const secure = process.env.NODE_ENV === "production";

export async function getSession(secret: string): Promise<SessionData | null> {
  const c = await cookies();
  const raw = c.get(SESSION_COOKIE)?.value;
  return raw ? decrypt<SessionData>(secret, raw) : null;
}

export async function setSession(secret: string, data: SessionData): Promise<void> {
  const c = await cookies();
  c.set(SESSION_COOKIE, encrypt(secret, data), {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 8, // 8 hours
  });
}

export async function clearSession(): Promise<void> {
  const c = await cookies();
  c.delete(SESSION_COOKIE);
}

export async function setOAuthState(secret: string, state: OAuthState): Promise<void> {
  const c = await cookies();
  c.set(OAUTH_COOKIE, encrypt(secret, state), {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 10, // 10 minutes to complete the handshake
  });
}

export async function takeOAuthState(secret: string): Promise<OAuthState | null> {
  const c = await cookies();
  const raw = c.get(OAUTH_COOKIE)?.value;
  if (!raw) return null;
  c.delete(OAUTH_COOKIE);
  return decrypt<OAuthState>(secret, raw);
}
