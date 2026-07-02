import { NextRequest, NextResponse } from "next/server";
import { getConfig } from "@/lib/priority/env";
import { exchangeCode, decodeIdName } from "@/lib/priority/oauth";
import { takeOAuthState, setSession } from "@/lib/priority/session";

export const runtime = "nodejs";

// OAuth redirect target: validate state, exchange the code (PKCE), store tokens
// in the encrypted session cookie, then return to the app.
export async function GET(req: NextRequest) {
  const cfg = getConfig();
  const home = cfg.appBaseUrl.replace(/\/$/, "");
  const url = new URL(req.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const err = url.searchParams.get("error");

  if (err) {
    return NextResponse.redirect(`${home}/?auth_error=${encodeURIComponent(err)}`);
  }
  if (!code || !state || !cfg.sessionSecret) {
    return NextResponse.redirect(`${home}/?auth_error=missing_code`);
  }

  const saved = await takeOAuthState(cfg.sessionSecret);
  if (!saved || saved.state !== state) {
    return NextResponse.redirect(`${home}/?auth_error=state_mismatch`);
  }

  try {
    const tokens = await exchangeCode(cfg, code, saved.verifier);
    const { sub, name } = decodeIdName(tokens.id_token);
    await setSession(cfg.sessionSecret, {
      accessToken: tokens.access_token,
      refreshToken: tokens.refresh_token,
      expiresAt: tokens.expires_in ? Date.now() + tokens.expires_in * 1000 : undefined,
      sub,
      name,
    });
    return NextResponse.redirect(`${home}/?connected=1`);
  } catch (e) {
    return NextResponse.redirect(
      `${home}/?auth_error=${encodeURIComponent(e instanceof Error ? e.message : "exchange_failed")}`
    );
  }
}
