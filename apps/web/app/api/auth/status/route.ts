import { NextResponse } from "next/server";
import { getConfig, isConfigured, canOAuth } from "@/lib/priority/env";
import { isConnected } from "@/lib/priority/auth";

export const runtime = "nodejs";

// Tells the client which mode to run in:
//  - demo:      nothing configured → use built-in mock data
//  - connect:   configured but the user still needs to log in
//  - live:      connected → queries hit real Priority
export async function GET() {
  const cfg = getConfig();
  if (!isConfigured(cfg)) {
    return NextResponse.json({ mode: "demo" });
  }
  const { connected, name, method } = await isConnected(cfg);
  if (connected) {
    return NextResponse.json({ mode: "live", name, method });
  }
  return NextResponse.json({ mode: "connect", canOAuth: canOAuth(cfg) });
}
