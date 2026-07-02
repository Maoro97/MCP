import { NextRequest, NextResponse } from "next/server";
import { getConfig, isConfigured } from "@/lib/priority/env";
import { getAuthHeader } from "@/lib/priority/auth";
import { odataGet, PriorityError } from "@/lib/priority/client";
import { getQuery, resolveIntent, listQueries, detectLang } from "@/lib/priority/queries";
import { aiResolveIntent, aiAvailable } from "@/lib/priority/ai";
import type { AssistantAnswer } from "@/lib/types";

export const runtime = "nodejs";

// Runs a predefined, read-only query against live Priority and returns a
// rendered AssistantAnswer (prose + widget + source). Hebrew questions get
// Hebrew answers. If ANTHROPIC_API_KEY is set, Claude picks the query
// (it never sees ERP data — only the question and the catalogue).
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
  const lang = detectLang(body.text ?? "");

  // Resolve which query to run: explicit intent > AI resolver > keywords.
  let intentId = body.intent;
  let arg = body.arg;
  if (!intentId && body.text) {
    const r = aiAvailable()
      ? await aiResolveIntent(body.text)
      : resolveIntent(body.text);
    if (r) {
      intentId = r.id;
      arg = r.arg;
    }
  }

  const def = intentId ? getQuery(intentId) : undefined;
  if (!def) {
    const names = listQueries()
      .map((q) => (lang === "he" ? q.labelHe : q.label))
      .join(", ");
    const answer: AssistantAnswer = {
      text:
        lang === "he"
          ? `אפשר לשאול אותי על הנתונים הבאים מ-Priority (קריאה בלבד): **${names}**. ` +
            `נסו למשל: *"הצג הזמנות ללקוח 10001"*, *"הצג לקוחות"* או *"פריטים"*.`
          : `I can run these read-only queries against your Priority data: **${names}**. ` +
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
    const answer = def.map(rows, { now, lang }, arg);
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
