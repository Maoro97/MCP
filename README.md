# Priority Chat

A branded, **read-only** chat assistant for the **Priority ERP** system, powered by an
**MCP server**. Business users (sales, finance, warehouse) ask questions in plain language
— "show open sales orders for customer 10001 this month" — and get clean, readable results
(tables, record cards, KPI tiles, charts), each with the exact Priority form it came from.

> **Status: Phase A — visual prototype.** The GUI is fully working against realistic
> **mocked** Priority data so the experience can be reviewed before wiring the live API.
> No LLM and no network calls yet. See the roadmap below.

## Why MCP

The core is a reusable **MCP server** that exposes Priority's OData REST API as read-only
tools. The chat app is just one consumer of it — the same tools also work in Claude Desktop
and Claude Code.

```
GUI (Next.js) ──▶ chat backend (Claude agent loop) ──▶ MCP server ──▶ Priority OData API
```

## Repository layout

```
apps/web              → Next.js GUI + (later) chat backend      ← this is what runs today
packages/mcp-server   → TS MCP server, Priority read-only tools  (Phase B)
packages/priority     → OData connector: auth, client, mapping   (Phase B)
packages/shared       → result-shape types shared by widgets     (graduates from apps/web/lib/types.ts)
```

## Run the prototype

```bash
pnpm install
pnpm dev
# open http://localhost:3000
```

Try the suggested starter questions, or ask things like:

- `A/R aging` — KPI tiles for accounts-receivable
- `open orders for customer 10001` — sortable data table
- `customer 10001 overview` — record card
- `parts below reorder point` — inventory table
- `sales trend last 6 months` — bar chart
- `top customers this quarter` — bar chart

Toggle **dark mode** and **RTL/Hebrew** from the top-right of the header.

## What's in the prototype

- **Generative result widgets** — the assistant returns structured data and the UI picks the
  right widget (`components/widgets/`), driven by a shared contract in `apps/web/lib/types.ts`.
- **Source chips** — every answer shows the Priority form + timestamp; hover for the OData query.
- **Simulated streaming** — tool-call indicator, then word-by-word prose, then the widget.
- **Themeable** — all colors are CSS variables in `app/globals.css`; swap the accent to rebrand.
- **RTL / Hebrew** first-class for the Israeli Priority market.

The mock "assistant" lives in `apps/web/lib/mock.ts` and is deliberately isolated so Phase C
can swap it for a real Claude + MCP loop without touching the rendering layer.

## Roadmap

- **Phase A ✅** — visual prototype (this).
- **Phase B** — TS MCP server + Priority OData connector (PAT auth) with read-only tools
  (`query_orders`, `query_customers`, `query_invoices`, `query_inventory`, capped generic
  `odata_query`, `describe_entities`); test against the Priority sandbox (`usdemo`).
- **Phase C** — wire the chat backend to the MCP server via a Claude agent loop; replace mocks
  with live data.
- **Phase D** — saved queries, entity explorer wired to `$metadata`, per-user Priority auth,
  Hebrew field labels from metadata, polish.

## Security (v1)

Read-only by design: MCP tools are GET-only, the generic query rejects non-read verbs, `$top`
is capped, and Priority credentials (PAT) stay server-side — never in the browser.
