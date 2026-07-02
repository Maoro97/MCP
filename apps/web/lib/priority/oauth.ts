import "server-only";
import { createHash, randomBytes } from "crypto";
import type { PriorityConfig } from "./env";
import { discoveryUrl, redirectUri } from "./env";

/*
 * OAuth2 Authorization-Code + PKCE for Priority. Endpoints are read from the
 * OpenID discovery document at runtime, so this keeps working across Priority
 * versions without hardcoding URLs. Only PKCE (public client, no secret) is used
 * — Priority supports only this flow.
 */

interface Discovery {
  authorization_endpoint: string;
  token_endpoint: string;
  issuer: string;
}

let cached: { url: string; doc: Discovery; at: number } | null = null;

export async function getDiscovery(cfg: PriorityConfig): Promise<Discovery> {
  const url = discoveryUrl(cfg);
  if (!url) throw new Error("OIDC issuer/discovery URL is not configured.");
  // Cache for 10 minutes.
  if (cached && cached.url === url && Date.now() - cached.at < 6e5) {
    return cached.doc;
  }
  const res = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" });
  if (!res.ok) {
    throw new Error(`OIDC discovery failed (${res.status}) at ${url}`);
  }
  const doc = (await res.json()) as Discovery;
  cached = { url, doc, at: Date.now() };
  return doc;
}

export function pkce(): { verifier: string; challenge: string } {
  const verifier = randomBytes(32).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  return { verifier, challenge };
}

export function randomState(): string {
  return randomBytes(16).toString("base64url");
}

export async function buildAuthorizeUrl(
  cfg: PriorityConfig,
  challenge: string,
  state: string
): Promise<string> {
  const { authorization_endpoint } = await getDiscovery(cfg);
  const p = new URLSearchParams({
    response_type: "code",
    client_id: cfg.oauthClientId!,
    redirect_uri: redirectUri(cfg),
    scope: cfg.oauthScope,
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
  });
  return `${authorization_endpoint}?${p.toString()}`;
}

export interface TokenSet {
  access_token: string;
  refresh_token?: string;
  expires_in?: number;
  id_token?: string;
}

export async function exchangeCode(
  cfg: PriorityConfig,
  code: string,
  verifier: string
): Promise<TokenSet> {
  const { token_endpoint } = await getDiscovery(cfg);
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    redirect_uri: redirectUri(cfg),
    client_id: cfg.oauthClientId!,
    code_verifier: verifier,
  });
  const res = await fetch(token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
    body,
    cache: "no-store",
  });
  if (!res.ok) {
    const t = await res.text().catch(() => "");
    throw new Error(`Token exchange failed (${res.status}): ${t.slice(0, 300)}`);
  }
  return (await res.json()) as TokenSet;
}

export async function refreshToken(
  cfg: PriorityConfig,
  refresh: string
): Promise<TokenSet> {
  const { token_endpoint } = await getDiscovery(cfg);
  const body = new URLSearchParams({
    grant_type: "refresh_token",
    refresh_token: refresh,
    client_id: cfg.oauthClientId!,
  });
  const res = await fetch(token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
    body,
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Token refresh failed (${res.status})`);
  return (await res.json()) as TokenSet;
}

/** Decode the (unverified) id_token payload for a display name — best effort. */
export function decodeIdName(idToken?: string): { sub?: string; name?: string } {
  if (!idToken) return {};
  try {
    const payload = idToken.split(".")[1];
    const json = JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
    return { sub: json.sub, name: json.name ?? json.preferred_username ?? json.email };
  } catch {
    return {};
  }
}
