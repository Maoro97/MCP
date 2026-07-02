# Priority Chat

A branded, **read-only** chat assistant for the **Priority ERP** system. Business users
(sales, finance, warehouse) ask questions in plain language — "show open sales orders for
customer 10001" — and get clean, readable results (tables, record cards, KPI tiles, charts),
each with the exact Priority form it came from.

> **Status:** runs in two modes.
> - **Demo mode** (default, nothing to configure): the full UX against realistic **mock** data.
> - **Live mode**: connects to a **real Priority** environment over its **OData REST API**,
>   authenticated via **OAuth2 (PKCE)**, running a curated set of **read-only** queries.

## Run it (demo mode)

```bash
# from the repo root
pnpm install
pnpm dev            # then open http://localhost:3000
```

On Windows without pnpm, use npm inside the app folder:

```cmd
cd apps\web
npm install
npm run dev
```

Try the starter prompts, or type `show customers`, `open orders for customer 10001`,
`A/R aging`, `parts below reorder point`, `sales trend last 6 months`. Toggle dark mode and
RTL/Hebrew from the header.

## Connect to real Priority (live mode)

1. **Copy the env template** and fill it in:
   ```bash
   cp apps/web/.env.example apps/web/.env.local
   ```
   `.env.local` is gitignored — your credentials never leave your machine and are never sent
   to the browser.

2. **Set your OData service root** (`PRIORITY_ODATA_URL`). Format:
   `https://{domain}/odata/Priority/{tabula.ini}/{company}`.

3. **Choose how to authenticate** (in `.env.local`, pick one):
   - **API username + password (simplest):** set `PRIORITY_API_USERNAME` and
     `PRIORITY_API_PASSWORD` — the API User Name from the Personnel File form in Priority
     (separate from the regular login name).
   - **Personal Access Token (v19.1+):** set `PRIORITY_PAT` — created in the
     "REST Interface Access Tokens" form. Sent as Basic auth with the literal password `PAT`,
     per Priority's spec.
   - **OAuth2 (per-user sign-in):** set `PRIORITY_OIDC_ISSUER` (your Priority domain),
     `PRIORITY_OAUTH_CLIENT_ID`, and `SESSION_SECRET`. In Priority, register an OAuth client
     and add the redirect URI **`http://localhost:3000/api/auth/callback`**. The app reads the
     authorize/token endpoints from `{issuer}/accounts/.well-known/openid-configuration`.
   - **Raw bearer token (testing):** `PRIORITY_ACCESS_TOKEN`.

4. **Restart** (`pnpm dev`). The app now shows a **Connect to Priority** screen (OAuth) or goes
   straight to live data (static token). Sign in, then ask your questions.

> **Field names:** Priority forms can be customised per site. The query definitions in
> `apps/web/lib/priority/queries.ts` use sensible default field names and fall back to whatever
> fields your data actually returns — tune them to your environment's `$metadata` as needed.

## Architecture

```
Browser (chat UI, widgets)
    │  POST /api/query          (never sees credentials)
    ▼
Next.js route handlers (server, Node runtime)
    ├─ /api/auth/*   OAuth2 PKCE login + encrypted httpOnly session cookie
    └─ /api/query    predefined read-only query → OData → rendered answer
    ▼
lib/priority/  ── read-only OData connector (GET-only, $top-capped)
    ▼
Priority ERP (OData REST API)
```

Key modules:
- `lib/priority/client.ts` — read-only OData client (issues **GET only**, caps `$top`).
- `lib/priority/oauth.ts` + `session.ts` — discovery-based OAuth2 PKCE; tokens stored in an
  AES-256-GCM encrypted, httpOnly cookie (server-side only).
- `lib/priority/queries.ts` — the catalogue of predefined queries + defensive widget mappers.
- `lib/types.ts` — the result-shape contract shared by the API and the UI widgets.
- `components/widgets/` — the "generative UI" (table, record card, KPI tiles, chart).

## Security

- **Read-only by design:** the connector only ever issues HTTP GET; there is no create/update/
  delete path. Every query is `$top`-capped.
- **Credentials stay server-side:** Priority tokens live in an encrypted httpOnly cookie or in
  `.env.local` — never in browser JavaScript, never committed.
- Live mode respects the signed-in user's own Priority permissions.

## Repository layout

```
apps/web/
  app/                Next.js app + API route handlers
  components/         chat UI, shell, generative widgets
  lib/
    priority/         OData connector, OAuth2, session, query catalogue (server-only)
    types.ts          shared result-shape contract
    mock.ts           demo-mode data + engine
```

## Roadmap

- ✅ Visual prototype (demo mode).
- ✅ Live read-only mode: OData connector + OAuth2 PKCE + predefined query catalogue.
- Extend the query catalogue (aggregations for aging/trends, purchase orders, suppliers).
- Optional AI layer: drop in a Claude agent loop for free-text questions over any entity.
- Package the connector as a standalone **MCP server** for use in Claude Desktop / Claude Code.
