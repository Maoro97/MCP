import "server-only";
import type { PriorityConfig } from "./env";

/*
 * Minimal read-only OData client for Priority.
 *
 * SECURITY: this module only ever issues HTTP GET. There is no code path here
 * that can create, update or delete data — the product is read-only by design.
 */

export interface ODataQuery {
  /** Entity set / form name, e.g. "ORDERS", "CUSTOMERS", or "CUSTOMERS('10001')". */
  entity: string;
  filter?: string;
  select?: string;
  expand?: string;
  orderby?: string;
  top?: number;
  /** OData aggregation, e.g. "aggregate(DEBIT with sum as Total)". */
  apply?: string;
}

export class PriorityError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: string
  ) {
    super(message);
    this.name = "PriorityError";
  }
}

export function buildUrl(cfg: PriorityConfig, q: ODataQuery): string {
  if (!cfg.odataUrl) {
    throw new PriorityError("PRIORITY_ODATA_URL is not configured", 500);
  }
  const base = cfg.odataUrl.replace(/\/$/, "");
  const params = new URLSearchParams();
  if (q.filter) params.set("$filter", q.filter);
  if (q.select) params.set("$select", q.select);
  if (q.expand) params.set("$expand", q.expand);
  if (q.orderby) params.set("$orderby", q.orderby);
  if (q.apply) params.set("$apply", q.apply);
  // Enforce the read-only row cap on every request.
  const top = Math.min(q.top ?? cfg.maxTop, cfg.maxTop);
  params.set("$top", String(top));

  const qs = params.toString();
  return `${base}/${q.entity}${qs ? `?${qs}` : ""}`;
}

interface ODataResponse<T> {
  value?: T[];
  [k: string]: unknown;
}

/**
 * Run a read-only OData GET. Returns the `value` array for collections, or the
 * single entity object wrapped in an array for keyed reads.
 */
export async function odataGet<T = Record<string, unknown>>(
  cfg: PriorityConfig,
  authHeader: string,
  q: ODataQuery
): Promise<T[]> {
  const url = buildUrl(cfg, q);
  let res: Response;
  try {
    res = await fetch(url, {
      method: "GET",
      headers: {
        Authorization: authHeader,
        Accept: "application/json",
      },
      // Never cache ERP data.
      cache: "no-store",
    });
  } catch (e) {
    throw new PriorityError(
      "Could not reach Priority. Check PRIORITY_ODATA_URL and your network.",
      502,
      e instanceof Error ? e.message : String(e)
    );
  }

  if (res.status === 401 || res.status === 403) {
    throw new PriorityError("Priority rejected the credentials (unauthorized).", 401);
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new PriorityError(
      `Priority returned ${res.status} for ${q.entity}.`,
      res.status,
      body.slice(0, 500)
    );
  }

  const json = (await res.json()) as ODataResponse<T> | T;
  if (json && typeof json === "object" && "value" in json && Array.isArray((json as ODataResponse<T>).value)) {
    return (json as ODataResponse<T>).value as T[];
  }
  // Keyed single-entity read.
  return [json as T];
}
