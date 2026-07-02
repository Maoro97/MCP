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
 *
 * Bilingual: every query carries Hebrew keywords and labels, and the summary
 * text is generated in the language of the question (ctx.lang).
 */

type Row = Record<string, unknown>;
export type Lang = "en" | "he";

export interface QueryContext {
  now: string;
  lang: Lang;
}

export interface QueryDef {
  id: string;
  /** Human label (used for the source chip + entity explorer). */
  label: string;
  labelHe: string;
  /** Short description of what the query does — also shown to the AI resolver. */
  description: string;
  /** Priority OData entity/form name. */
  form: string;
  /** Keywords (English + Hebrew) used to match free text to this query. */
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
  const label = ctx.lang === "he" ? def.labelHe : def.label;
  const rowsWord = ctx.lang === "he" ? "שורות" : "rows";
  return {
    text: summary,
    widget: {
      kind: "table",
      title: label,
      columns: cols,
      rows: toTableRows(rows, cols),
      footnote: `${rows.length} ${rowsWord}`,
    },
    source: { form: def.form, label, asOf: ctx.now },
  };
}

function pickFields(row: Row, prefer: string[]): RecordField[] {
  const keys = prefer.filter((k) => k in row);
  const use = keys.length ? keys : Object.keys(row).slice(0, 8);
  return use.map((k) => ({ label: k, value: fmt(row[k]) }));
}

/** Bilingual "found N X" summary. */
function foundSummary(
  ctx: QueryContext,
  n: number,
  en: { singular: string; plural: string; suffix?: string },
  he: { singular: string; plural: string; suffix?: string }
): string {
  if (ctx.lang === "he") {
    if (n === 0) return `לא נמצאו ${he.plural}${he.suffix ?? ""}.`;
    if (n === 1) return `נמצאה ${he.singular} אחת${he.suffix ?? ""}.`;
    return `נמצאו **${n}** ${he.plural}${he.suffix ?? ""}.`;
  }
  if (n === 0) return `No ${en.plural} matched${en.suffix ?? ""}.`;
  return `Found **${n}** ${n === 1 ? en.singular : en.plural}${en.suffix ?? ""}.`;
}

// ---- query catalogue --------------------------------------------------------

export const QUERIES: QueryDef[] = [
  {
    id: "customers",
    label: "Customers",
    labelHe: "לקוחות",
    description: "List customers, optionally filtered by customer number.",
    form: "CUSTOMERS",
    keywords: [
      "customer", "customers", "client", "accounts",
      "לקוח", "לקוחות", "כרטיס לקוח",
    ],
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
        foundSummary(ctx, rows.length,
          { singular: "customer", plural: "customers" },
          { singular: "לקוח", plural: "לקוחות" })
      ),
  },
  {
    id: "customer_detail",
    label: "Customer",
    labelHe: "כרטיס לקוח",
    description:
      "Show one customer's details (balance, terms, contact) by customer number. Requires a customer number argument.",
    form: "CUSTOMERS",
    keywords: [
      "customer detail", "overview", "profile",
      "פרטי לקוח", "כרטיס", "יתרת לקוח",
    ],
    build: (arg) => ({ entity: `CUSTOMERS('${arg ?? ""}')` }),
    map: (rows, ctx, arg) => {
      const row = rows[0];
      if (!row) {
        return {
          text:
            ctx.lang === "he"
              ? `לא נמצא לקוח **${arg}**.`
              : `No customer found for **${arg}**.`,
        };
      }
      const title =
        (row["CUSTDES"] as string) || (row["CUSTNAME"] as string) || "Customer";
      return {
        text:
          ctx.lang === "he"
            ? `פרטי לקוח **${arg}**.`
            : `Overview of customer **${arg}**.`,
        widget: {
          kind: "record",
          title,
          subtitle: row["CUSTNAME"]
            ? ctx.lang === "he"
              ? `לקוח ${row["CUSTNAME"]}`
              : `Customer ${row["CUSTNAME"]}`
            : undefined,
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
        source: {
          form: "CUSTOMERS",
          label: ctx.lang === "he" ? "כרטיס לקוח" : "Customer",
          asOf: ctx.now,
        },
      };
    },
  },
  {
    id: "orders",
    label: "Sales Orders",
    labelHe: "הזמנות לקוח",
    description:
      "List sales orders, newest first. Optional argument: customer number to filter by.",
    form: "ORDERS",
    keywords: [
      "order", "orders", "sales order", "so",
      "הזמנה", "הזמנות", "הזמנות לקוח", "הזמנות פתוחות",
    ],
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
        foundSummary(ctx, rows.length,
          { singular: "sales order", plural: "sales orders", suffix: arg ? ` for customer ${arg}` : "" },
          { singular: "הזמנה", plural: "הזמנות", suffix: arg ? ` ללקוח ${arg}` : "" })
      ),
  },
  {
    id: "invoices",
    label: "A/R Invoices",
    labelHe: "חשבוניות מס",
    description:
      "List accounts-receivable invoices, newest first. Optional argument: customer number.",
    form: "AINVOICES",
    keywords: [
      "invoice", "invoices", "receivable", "a/r", "ar", "billing",
      "חשבונית", "חשבוניות", "חשבוניות מס", "חוב", "גבייה",
    ],
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
        foundSummary(ctx, rows.length,
          { singular: "invoice", plural: "invoices" },
          { singular: "חשבונית", plural: "חשבוניות" })
      ),
  },
  {
    id: "parts",
    label: "Parts / Inventory",
    labelHe: "פריטים / מלאי",
    description:
      "List parts from the part catalogue. Optional argument: part number.",
    form: "LOGPART",
    keywords: [
      "part", "parts", "inventory", "stock", "item", "sku",
      "פריט", "פריטים", "מלאי", "מקט", 'מק"ט', "קטלוג",
    ],
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
        foundSummary(ctx, rows.length,
          { singular: "part", plural: "parts" },
          { singular: "פריט", plural: "פריטים" })
      ),
  },
];

export function listQueries() {
  return QUERIES.map((q) => ({
    id: q.id,
    label: q.label,
    labelHe: q.labelHe,
    description: q.description,
    form: q.form,
  }));
}

export function getQuery(id: string): QueryDef | undefined {
  return QUERIES.find((q) => q.id === id);
}

/** True when the text contains Hebrew characters. */
export function detectLang(text: string): Lang {
  return /[֐-׿]/.test(text) ? "he" : "en";
}

/** Map free text → a query id + optional argument (keyword fallback, EN + HE). */
export function resolveIntent(
  text: string
): { id: string; arg?: string } | null {
  const q = text.toLowerCase();
  const num = text.match(/\b\d{3,}\b/)?.[0];
  const has = (...ks: string[]) => ks.some((k) => q.includes(k));

  if (has("customer", "client", "לקוח") && num)
    return { id: "customer_detail", arg: num };
  if (has("order", "sales order", "הזמנ")) return { id: "orders", arg: num };
  if (has("invoice", "receivable", "a/r", "ar ", "billing", "חשבונית", "חשבוניות", "גביי", "חוב"))
    return { id: "invoices", arg: num };
  if (has("part", "inventory", "stock", "item", "sku", "פריט", "מלאי", "מקט", 'מק"ט', "קטלוג"))
    return { id: "parts", arg: num };
  if (has("customer", "client", "accounts", "לקוח"))
    return { id: "customers", arg: undefined };
  return null;
}
