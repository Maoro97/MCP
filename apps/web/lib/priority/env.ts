import "server-only";

/*
 * Server-only Priority + OAuth configuration, read from environment variables.
 * Nothing here is ever bundled into the browser (guarded by "server-only").
 *
 * Copy apps/web/.env.example to apps/web/.env.local and fill these in.
 */

function opt(name: string): string | undefined {
  const v = process.env[name];
  return v && v.trim() ? v.trim() : undefined;
}

export interface PriorityConfig {
  /** Full OData service root, e.g.
   *  https://t.eu.priority-connect.online/odata/Priority/tabbtd38.ini/usdemo */
  odataUrl?: string;
  /** OIDC issuer/domain, e.g. https://t.eu.priority-connect.online
   *  Discovery is issuer + /accounts/.well-known/openid-configuration */
  oidcIssuer?: string;
  /** Explicit discovery URL (overrides oidcIssuer if set). */
  oidcDiscoveryUrl?: string;
  oauthClientId?: string;
  oauthScope: string;
  /** Public base URL of THIS app, for the OAuth redirect_uri. */
  appBaseUrl: string;
  /** Secret used to encrypt the session cookie (>= 32 chars). */
  sessionSecret?: string;
  /** Dev fallback: a bearer token to use directly, skipping the OAuth flow. */
  staticAccessToken?: string;
  /** Max rows any single query may pull back (read-only safety cap). */
  maxTop: number;
}

export function getConfig(): PriorityConfig {
  return {
    odataUrl: opt("PRIORITY_ODATA_URL"),
    oidcIssuer: opt("PRIORITY_OIDC_ISSUER"),
    oidcDiscoveryUrl: opt("PRIORITY_OIDC_DISCOVERY_URL"),
    oauthClientId: opt("PRIORITY_OAUTH_CLIENT_ID"),
    oauthScope: opt("PRIORITY_OAUTH_SCOPE") ?? "openid profile offline_access",
    appBaseUrl: opt("APP_BASE_URL") ?? "http://localhost:3000",
    sessionSecret: opt("SESSION_SECRET"),
    staticAccessToken: opt("PRIORITY_ACCESS_TOKEN"),
    maxTop: Number(opt("PRIORITY_MAX_TOP") ?? "50"),
  };
}

export function discoveryUrl(cfg: PriorityConfig): string | undefined {
  if (cfg.oidcDiscoveryUrl) return cfg.oidcDiscoveryUrl;
  if (cfg.oidcIssuer)
    return (
      cfg.oidcIssuer.replace(/\/$/, "") +
      "/accounts/.well-known/openid-configuration"
    );
  return undefined;
}

export function redirectUri(cfg: PriorityConfig): string {
  return cfg.appBaseUrl.replace(/\/$/, "") + "/api/auth/callback";
}

/** True when at least a data source is configured (OData URL present). */
export function isConfigured(cfg: PriorityConfig): boolean {
  return Boolean(cfg.odataUrl);
}

/** True when the OAuth login flow can be started. */
export function canOAuth(cfg: PriorityConfig): boolean {
  return Boolean(discoveryUrl(cfg) && cfg.oauthClientId && cfg.sessionSecret);
}
