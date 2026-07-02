import { NextResponse } from "next/server";
import { getConfig, canOAuth } from "@/lib/priority/env";
import { pkce, randomState, buildAuthorizeUrl } from "@/lib/priority/oauth";
import { setOAuthState } from "@/lib/priority/session";

export const runtime = "nodejs";

// Starts the OAuth2 + PKCE handshake: stash verifier/state in a short-lived
// httpOnly cookie, then redirect the user to Priority's login.
export async function GET() {
  const cfg = getConfig();
  if (!canOAuth(cfg)) {
    return NextResponse.json(
      { error: "OAuth is not configured. Set PRIORITY_OIDC_ISSUER, PRIORITY_OAUTH_CLIENT_ID and SESSION_SECRET." },
      { status: 400 }
    );
  }
  const { verifier, challenge } = pkce();
  const state = randomState();
  await setOAuthState(cfg.sessionSecret!, { verifier, state });

  try {
    const url = await buildAuthorizeUrl(cfg, challenge, state);
    return NextResponse.redirect(url);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Failed to start login." },
      { status: 502 }
    );
  }
}
