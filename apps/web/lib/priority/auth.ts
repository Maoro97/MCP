import "server-only";
import type { PriorityConfig } from "./env";
import { getSession, setSession } from "./session";
import { refreshToken } from "./oauth";

/*
 * Resolves a usable bearer token for an OData request:
 *  1. PRIORITY_ACCESS_TOKEN (dev fallback), else
 *  2. the encrypted session token, refreshing it if expired.
 * Returns null when the user is not connected.
 */
export async function getAccessToken(
  cfg: PriorityConfig
): Promise<string | null> {
  if (cfg.staticAccessToken) return cfg.staticAccessToken;
  if (!cfg.sessionSecret) return null;

  const session = await getSession(cfg.sessionSecret);
  if (!session) return null;

  const expired = session.expiresAt ? Date.now() > session.expiresAt - 30_000 : false;
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
      return updated.accessToken;
    } catch {
      return null; // refresh failed → force reconnect
    }
  }
  return session.accessToken;
}

export async function isConnected(cfg: PriorityConfig): Promise<{
  connected: boolean;
  name?: string;
}> {
  if (cfg.staticAccessToken) return { connected: true, name: "Static token" };
  if (!cfg.sessionSecret) return { connected: false };
  const session = await getSession(cfg.sessionSecret);
  return { connected: Boolean(session?.accessToken), name: session?.name };
}
