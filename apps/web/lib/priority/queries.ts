import type {
  AssistantAnswer,
  TableColumn,
  TableRow,
  RecordField,
} from "../types";
import type { ODataQuery } from "./client";

/*
 * The catalogue of read-only queries the app can run against live Priority.
 *
 * IMPORTANT: Priority field names can vary by installation/customisation. The
 * `columns` below are sensible defaults; the mappers are DEFENSIVE — if a
 * preferred field is absent they fall back to whatever fields the row actually
 * has, so you still see real data. Tune the entity/field names here to match
 * your environment's $metadata.
 */

type Row = Record<string, unknown>;

export interface QueryContext {
  /** Optional Priority form/label overrides. */
  now: string;
}

export interface QueryDef {
  id: string;
  /** Human label (used for the source chip + entity explorer). */
  label: string;
  /** Priority OData entity/form name. */
  form: string;
  /** Keywords used to match free text to this query. */
  keywords: string[];
  /** Build the OData request. `arg` is an optional extracted parameter (e.g. a customer no.). */
  build: (arg?: string) => ODataQuery;
  /** Render rows into an assistant answer. */
  map: (rows: Row[], ctx: QueryContext, arg?: string) => AssistantAnswer;
  /** Preferred table columns (auto-fallback if absent). */
  columns?: TableColumn[];
}

// ---- helpers ----------------------------------------------------------------

const isNum = (v: unknown): v is number => typeof v === "number";

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (isNum(v)) return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return String(v);
}

/** Choose columns that actually exist in the data, else derive from the first row. */
function resolveColumns(rows: Row[], preferred?: TableColumn[]): TableColumn[] {
  if (rows.length === 0) return preferred ?? [];
  const present = new Set(Object.keys(rows[0]));
  const chosen = (preferred ?? []).filter((c) => present.has(c.key));
  if (chosen.length > 0) return chosen;
  // Fallback: first up-to-6 primitive fields.
  return Object.keys(rows[0])
    .filter((k) => {
      const t = typeof rows[0][k];
      return t === "string" || t === "number" || t === "boolean";
    })
    .slice(0, 6)
    .map((k) => ({ key: k, label: k, numeric: isNum(rows[0][k]) }));
}

function toTableRows(rows: Row[], cols: TableColumn[]): TableRow[] {
  return rows.map((r) => ({
    cells: Object.fromEntries(
      cols.map((c) => [c.key, isNum(r[c.key]) ? (r[c.key] as number) : fmt(r[c.key])])
    ),
  }));
}

function tableAnswer(
  def: QueryDef,
  rows: Row[],
  ctx: QueryContext,
  summary: string
): AssistantAnswer {
  const cols = resolveColumns(rows, def.columns);
  return {
    text: summary,
    widget: {
      kind: "table",
      title: def.label,
      columns: cols,
      rows: toTableRows(rows, cols),
      footnote: `${rows.length} row${rows.length === 1 ? "" : "s"}`,
    },
    source: { form: def.form, label: def.label, asOf: ctx.now },
  };
}

function pickFields(row: Row, prefer: string[]): RecordField[] {
  const keys = prefer.filter((k) => k in row);
  const use = keys.length ? keys : Object.keys(row).slice(0, 8);
  return use.map((k) => ({ label: k, value: fmt(row[k]) }));
}

// ---- query catalogue --------------------------------------------------------

export const QUERIES: QueryDef[] = [
  {
    id: "customers",
    label: "Customers",
    form: "CUSTOMERS",
    keywords: ["customer", "customers", "client", "accounts"],
    columns: [
      { key: "CUSTNAME", label: "Customer" },
      { key: "CUSTDES", label: "Name" },
      { key: "BALANCE", label: "Balance", numeric: true },
      { key: "PHONE", label: "Phone" },
    ],
    build: (arg) => ({
      entity: "CUSTOMERS",
      filter: arg ? `CUSTNAME eq '${arg}'` : undefined,
      orderby: "CUSTNAME",
    }),
    map: (rows, ctx) =>
      tableAnswer(
        QUERIES[0],
        rows,
        ctx,
        rows.length
          ? `Found **${rows.length}** customer${rows.length === 1 ? "" : "s"}.`
          : "No customers matched."
      ),
  },
  {
    id: "customer_detail",
    label: "Customer",
    form: "CUSTOMERS",
    keywords: ["customer detail", "overview", "profile"],
    build: (arg) => ({ entity: `CUSTOMERS('${arg ?? ""}')` }),
    map: (rows, ctx, arg) => {
      const row = rows[0];
      if (!row) {
        return { text: `No customer found for **${arg}**.` };
      }
      const title =
        (row["CUSTDES"] as string) || (row["CUSTNAME"] as string) || "Customer";
      return {
        text: `Overview of customer **${arg}**.`,
        widget: {
          kind: "record",
          title,
          subtitle: row["CUSTNAME"] ? `Customer ${row["CUSTNAME"]}` : undefined,
          fields: pickFields(row, [
            "CUSTNAME",
            "CUSTDES",
            "BALANCE",
            "MAXOBLIGO",
            "PAYDES",
            "PHONE",
            "ADDRESS",
            "STATE",
          ]),
        },
        source: { form: "CUSTOMERS", label: "Customer", asOf: ctx.now },
      };
    },
  },
  {
    id: "orders",
    label: "Sales Orders",
    form: "ORDERS",
    keywords: ["order", "orders", "sales order", "so"],
    columns: [
      { key: "ORDNAME", label: "Order" },
      { key: "CUSTNAME", label: "Customer" },
      { key: "CDES", label: "Name" },
      { key: "CURDATE", label: "Date" },
      { key: "ORDSTATUSDES", label: "Status" },
      { key: "QPRICE", label: "Total", numeric: true },
    ],
    build: (arg) => ({
      entity: "ORDERS",
      filter: arg ? `CUSTNAME eq '${arg}'` : undefined,
      orderby: "CURDATE desc",
    }),
    map: (rows, ctx, arg) =>
      tableAnswer(
        QUERIES[2],
        rows,
        ctx,
        rows.length
          ? `Found **${rows.length}** sales order${rows.length === 1 ? "" : "s"}${
              arg ? ` for customer ${arg}` : ""
            }.`
          : `No sales orders found${arg ? ` for customer ${arg}` : ""}.`
      ),
  },
  {
    id: "invoices",
    label: "A/R Invoices",
    form: "AINVOICES",
    keywords: ["invoice", "invoices", "receivable", "a/r", "ar", "billing"],
    columns: [
      { key: "IVNUM", label: "Invoice" },
      { key: "CUSTNAME", label: "Customer" },
      { key: "IVDATE", label: "Date" },
      { key: "DEBIT", label: "Amount", numeric: true },
      { key: "PAID", label: "Paid" },
    ],
    build: (arg) => ({
      entity: "AINVOICES",
      filter: arg ? `CUSTNAME eq '${arg}'` : undefined,
      orderby: "IVDATE desc",
    }),
    map: (rows, ctx) =>
      tableAnswer(
        QUERIES[3],
        rows,
        ctx,
        rows.length
          ? `Found **${rows.length}** invoice${rows.length === 1 ? "" : "s"}.`
          : "No invoices matched."
      ),
  },
  {
    id: "parts",
    label: "Parts / Inventory",
    form: "LOGPART",
    keywords: ["part", "parts", "inventory", "stock", "item", "sku"],
    columns: [
      { key: "PARTNAME", label: "Part" },
      { key: "PARTDES", label: "Description" },
      { key: "FAMILYNAME", label: "Family" },
      { key: "UNITNAME", label: "Unit" },
    ],
    build: (arg) => ({
      entity: "LOGPART",
      filter: arg ? `PARTNAME eq '${arg}'` : undefined,
      orderby: "PARTNAME",
    }),
    map: (rows, ctx) =>
      tableAnswer(
        QUERIES[4],
        rows,
        ctx,
        rows.length
          ? `Found **${rows.length}** part${rows.length === 1 ? "" : "s"}.`
          : "No parts matched."
      ),
  },
];

export function listQueries() {
  return QUERIES.map((q) => ({ id: q.id, label: q.label, form: q.form }));
}

export function getQuery(id: string): QueryDef | undefined {
  return QUERIES.find((q) => q.id === id);
}

/** Map free text → a query id + optional argument (e.g. a customer/part number). */
export function resolveIntent(
  text: string
): { id: string; arg?: string } | null {
  const q = text.toLowerCase();
  const num = text.match(/\b\d{3,}\b/)?.[0];
  const has = (...ks: string[]) => ks.some((k) => q.includes(k));

  if (has("customer", "client") && num) return { id: "customer_detail", arg: num };
  if (has("order", "sales order")) return { id: "orders", arg: num };
  if (has("invoice", "receivable", "a/r", "ar ", "billing")) return { id: "invoices", arg: num };
  if (has("part", "inventory", "stock", "item", "sku")) return { id: "parts", arg: num };
  if (has("customer", "client", "accounts")) return { id: "customers", arg: undefined };
  return null;
}
