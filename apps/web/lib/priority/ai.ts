import "server-only";
import Anthropic from "@anthropic-ai/sdk";
import { listQueries, resolveIntent } from "./queries";

/*
 * Optional AI layer: when ANTHROPIC_API_KEY is set, free-text questions
 * (Hebrew or English) are mapped to a predefined query by Claude instead of
 * keyword matching.
 *
 * PRIVACY / SAFETY BY DESIGN:
 *  - Claude sees ONLY the user's question and the catalogue of query names —
 *    never any ERP data. Data flows exclusively server ↔ Priority.
 *  - Claude can only CHOOSE from the read-only catalogue; it cannot compose
 *    raw OData, so the GET-only guarantee is preserved.
 */

const MODEL = process.env.CLAUDE_MODEL?.trim() || "claude-opus-4-8";

let client: Anthropic | null = null;

export function aiAvailable(): boolean {
  return Boolean(process.env.ANTHROPIC_API_KEY?.trim());
}

function getClient(): Anthropic {
  if (!client) client = new Anthropic();
  return client;
}

const OUTPUT_SCHEMA = {
  type: "object" as const,
  properties: {
    intent: {
      type: ["string", "null"],
      description: "The id of the matching query, or null if none fits.",
    },
    arg: {
      type: ["string", "null"],
      description:
        "Extracted argument for the query (customer number, part number), or null.",
    },
  },
  required: ["intent", "arg"],
  additionalProperties: false,
};

export interface ResolvedIntent {
  id: string;
  arg?: string;
}

/**
 * Resolve a free-text question (Hebrew/English) to a catalogue query.
 * Falls back to keyword matching if the API call fails for any reason.
 */
export async function aiResolveIntent(
  text: string
): Promise<ResolvedIntent | null> {
  if (!aiAvailable()) return resolveIntent(text);

  const catalogue = listQueries()
    .map(
      (q) =>
        `- id: ${q.id} | ${q.label} / ${q.labelHe} (Priority form ${q.form}): ${q.description}`
    )
    .join("\n");

  try {
    const response = await getClient().messages.create({
      model: MODEL,
      max_tokens: 256,
      system:
        "You route questions about a Priority ERP system to one of a fixed set of read-only queries. " +
        "Questions may be in Hebrew or English. Choose the single best-matching query id and extract " +
        "its argument if present (e.g. a customer or part number). If no query fits, return intent null. " +
        "Available queries:\n" +
        catalogue,
      output_config: {
        format: {
          type: "json_schema",
          schema: OUTPUT_SCHEMA,
        },
      },
      messages: [{ role: "user", content: text }],
    });

    const block = response.content.find((b) => b.type === "text");
    if (!block || block.type !== "text") return resolveIntent(text);
    const parsed = JSON.parse(block.text) as {
      intent: string | null;
      arg: string | null;
    };
    if (!parsed.intent) return null;
    return { id: parsed.intent, arg: parsed.arg ?? undefined };
  } catch {
    // Any API problem (bad key, network, rate limit) → keyword fallback.
    return resolveIntent(text);
  }
}
