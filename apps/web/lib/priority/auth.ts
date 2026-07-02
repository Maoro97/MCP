import "server-only";
import type { PriorityConfig } from "./env";
import { getSession, setSession } from "./session";
import { refreshToken } from "./oauth";

/*
 * Resolves the Authorization header for an OData request. Priority supports
 * several schemes; we check in this order:
 *
 *  1. PRIORITY_ACCESS_TOKEN          → "Bearer {token}"        (dev/testing)
 *  2. PRIORITY_PAT                   → "Basic {pat}:PAT"       (Personal Access
 *     Token, v19.1+ — Priority expects Basic auth with the PAT as the username
 *     and the literal string "PAT" as the password)
 *  3. PRIORITY_API_USERNAME/PASSWORD → "Basic {user}:{pass}"   (API user from
 *     the Personnel File form)
 *  4. OAuth session cookie           → "Bearer {access_token}" (refreshing if
 *     expired)
 *
 * Returns null when no credentials are available (user must connect).
 */

const basic = (user: string, pass: string) =>
  "Basic " + Buffer.from(`${user}:${pass}`).toString("base64");

export type AuthMethod = "static" | "pat" | "basic" | "oauth";

export function envAuthHeader(
  cfg: PriorityConfig
): { header: string; method: AuthMethod } | null {
  if (cfg.staticAccessToken)
    return { header: `Bearer ${cfg.staticAccessToken}`, method: "static" };
  if (cfg.personalAccessToken)
    return { header: basic(cfg.personalAccessToken, "PAT"), method: "pat" };
  if (cfg.apiUsername && cfg.apiPassword)
    return { header: basic(cfg.apiUsername, cfg.apiPassword), method: "basic" };
  return null;
}

export async function getAuthHeader(
  cfg: PriorityConfig
): Promise<string | null> {
  const env = envAuthHeader(cfg);
  if (env) return env.header;
  if (!cfg.sessionSecret) return null;

  const session = await getSession(cfg.sessionSecret);
  if (!session) return null;

  const expired = session.expiresAt
    ? Date.now() > session.expiresAt - 30_000
    : false;
  if (expired && session.refreshToken) {
    try {
      const t = await refreshToken(cfg, session.refreshToken);
      const updated = {
        ...session,
        accessToken: t.access_token,
        refreshToken: t.refresh_token ?? session.refreshToken,
        expiresAt: t.expires_in ? Date.now() + t.expires_in * 1000 : undefined,
      };
      await setSession(cfg.sessionSecret, updated);
      return `Bearer ${updated.accessToken}`;
    } catch {
      return null; // refresh failed → force reconnect
    }
  }
  return `Bearer ${session.accessToken}`;
}

const METHOD_LABEL: Record<AuthMethod, string> = {
  static: "API token",
  pat: "Access token",
  basic: "API user",
  oauth: "OAuth",
};

export async function isConnected(cfg: PriorityConfig): Promise<{
  connected: boolean;
  name?: string;
  method?: AuthMethod;
}> {
  const env = envAuthHeader(cfg);
  if (env)
    return { connected: true, name: METHOD_LABEL[env.method], method: env.method };
  if (!cfg.sessionSecret) return { connected: false };
  const session = await getSession(cfg.sessionSecret);
  return {
    connected: Boolean(session?.accessToken),
    name: session?.name,
    method: "oauth",
  };
}
