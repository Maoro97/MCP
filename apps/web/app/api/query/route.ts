import { NextRequest, NextResponse } from "next/server";
import { getConfig, isConfigured } from "@/lib/priority/env";
import { getAuthHeader } from "@/lib/priority/auth";
import { odataGet, PriorityError } from "@/lib/priority/client";
import { getQuery, resolveIntent, listQueries } from "@/lib/priority/queries";
import type { AssistantAnswer } from "@/lib/types";

export const runtime = "nodejs";

// Runs a predefined, read-only query against live Priority and returns a
// rendered AssistantAnswer (prose + widget + source).
export async function POST(req: NextRequest) {
  const cfg = getConfig();
  if (!isConfigured(cfg)) {
    return NextResponse.json({ error: "Priority is not configured." }, { status: 400 });
  }

  const body = (await req.json().catch(() => ({}))) as {
    text?: string;
    intent?: string;
    arg?: string;
  };

  // Resolve which query to run.
  let intentId = body.intent;
  let arg = body.arg;
  if (!intentId && body.text) {
    const r = resolveIntent(body.text);
    if (r) {
      intentId = r.id;
      arg = r.arg;
    }
  }

  const def = intentId ? getQuery(intentId) : undefined;
  if (!def) {
    const names = listQueries().map((q) => q.label).join(", ");
    const answer: AssistantAnswer = {
      text:
        `I can run these read-only queries against your Priority data: **${names}**. ` +
        `Try e.g. *"open orders for customer 10001"*, *"show customers"*, or *"parts"*.`,
    };
    return NextResponse.json({ answer });
  }

  const auth = await getAuthHeader(cfg);
  if (!auth) {
    return NextResponse.json({ error: "not_connected" }, { status: 401 });
  }

  try {
    const rows = await odataGet(cfg, auth, def.build(arg));
    const now = new Date().toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
    const answer = def.map(rows, { now }, arg);
    return NextResponse.json({ answer });
  } catch (e) {
    if (e instanceof PriorityError) {
      if (e.status === 401) {
        return NextResponse.json({ error: "not_connected" }, { status: 401 });
      }
      // Surface Priority's own error body — it usually names the exact
      // form/field problem, which is what a consultant needs to tune queries.
      const detail = e.detail
        ? `\n\nPriority says: ${e.detail.replace(/\s+/g, " ").trim()}`
        : "";
      return NextResponse.json(
        { answer: { text: `⚠️ ${e.message}${detail}` } as AssistantAnswer },
        { status: 200 }
      );
    }
    return NextResponse.json(
      { answer: { text: "⚠️ Something went wrong running that query." } },
      { status: 200 }
    );
  }
}
