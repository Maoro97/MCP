import type { AssistantAnswer, Widget } from "./types";

/*
 * Phase-A mock "assistant". No LLM, no network — a keyword-matched engine that
 * returns realistic Priority-shaped answers so we can feel the full UX. In
 * Phase C this module is replaced by a Claude agent loop calling the MCP tools;
 * the returned `AssistantAnswer` shape stays identical.
 */

export interface EntityInfo {
  form: string;
  label: string;
  count: string;
}

/** Priority forms exposed as read-only queryable entities (entity explorer). */
export const ENTITIES: EntityInfo[] = [
  { form: "ORDERS", label: "Sales Orders", count: "1,284" },
  { form: "CUSTOMERS", label: "Customers", count: "612" },
  { form: "AINVOICES", label: "A/R Invoices", count: "3,940" },
  { form: "LOGPART", label: "Parts / Inventory", count: "2,157" },
  { form: "PORDERS", label: "Purchase Orders", count: "498" },
  { form: "SUPPLIERS", label: "Suppliers", count: "203" },
];

export interface RolePrompt {
  role: string;
  prompts: string[];
}

/** Starter questions on the empty state, grouped by business role. */
export const ROLE_PROMPTS: RolePrompt[] = [
  {
    role: "Sales",
    prompts: [
      "Show open sales orders for customer 10001 this month",
      "Which customers ordered the most this quarter?",
    ],
  },
  {
    role: "Finance",
    prompts: [
      "What's my A/R aging right now?",
      "Show overdue invoices over ₪10,000",
    ],
  },
  {
    role: "Warehouse",
    prompts: [
      "Which parts are below reorder point?",
      "Show stock levels for part 6801-A",
    ],
  },
];

export const SAVED_QUERIES = [
  "Open orders this week",
  "Top 10 customers by revenue",
  "Parts below reorder point",
];

export const HISTORY = [
  "A/R aging summary",
  "Customer 10001 overview",
  "Overdue invoices > ₪10k",
  "Sales trend last 6 months",
];

interface EngineResult {
  toolLabel: string;
  answer: AssistantAnswer;
}

const nowStamp = () =>
  new Date().toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });

// ---- Canned scenarios --------------------------------------------------------

function openOrders(): EngineResult {
  const widget: Widget = {
    kind: "table",
    title: "Open sales orders · customer 10001",
    columns: [
      { key: "ord", label: "Order" },
      { key: "date", label: "Date" },
      { key: "items", label: "Lines", numeric: true },
      { key: "total", label: "Total", numeric: true },
    ],
    rows: [
      { cells: { ord: "SO25-000481", date: "01 Jul", items: 6, total: "₪48,200" }, status: { label: "Open", tone: "pos" } },
      { cells: { ord: "SO25-000474", date: "28 Jun", items: 2, total: "₪12,750" }, status: { label: "Partial", tone: "warn" } },
      { cells: { ord: "SO25-000455", date: "22 Jun", items: 9, total: "₪91,030" }, status: { label: "Open", tone: "pos" } },
      { cells: { ord: "SO25-000441", date: "15 Jun", items: 1, total: "₪3,400" }, status: { label: "Open", tone: "pos" } },
    ],
    footnote: "4 open orders · ₪155,380 total",
  };
  return {
    toolLabel: "Querying Sales Orders",
    answer: {
      text:
        "Customer **10001 — Tech Solutions Ltd** has **4 open sales orders** this month totalling **₪155,380**. One order (SO25-000474) is partially shipped; the rest are fully open.",
      widget,
      source: {
        form: "ORDERS",
        label: "Sales Orders",
        asOf: nowStamp(),
        odata: "ORDERS?$filter=CUST eq '10001' and ORDSTATUSDES eq 'Open'&$orderby=CURDATE desc",
      },
    },
  };
}

function customerOverview(): EngineResult {
  const widget: Widget = {
    kind: "record",
    title: "Tech Solutions Ltd",
    subtitle: "Customer 10001 · Tel Aviv",
    status: { label: "Active", tone: "pos" },
    fields: [
      { label: "Balance", value: "₪128,940", emphasize: true },
      { label: "Credit limit", value: "₪250,000" },
      { label: "Open orders", value: "4" },
      { label: "Payment terms", value: "Net 30" },
      { label: "Agent", value: "D. Cohen" },
      { label: "Last order", value: "01 Jul 2026" },
    ],
  };
  return {
    toolLabel: "Querying Customers",
    answer: {
      text:
        "Here's an overview of **customer 10001 — Tech Solutions Ltd**. They're within their credit limit with a current balance of **₪128,940** and 4 open orders.",
      widget,
      source: {
        form: "CUSTOMERS",
        label: "Customers",
        asOf: nowStamp(),
        odata: "CUSTOMERS('10001')?$select=CUSTNAME,CUSTDES,BALANCE,MAXOBLIGO,PAYCODE",
      },
    },
  };
}

function arAging(): EngineResult {
  const kpis: Widget = {
    kind: "kpis",
    tiles: [
      { label: "Total A/R", value: "₪1.24M" },
      { label: "Overdue", value: "₪312K", delta: "25% of balance", tone: "warn" },
      { label: "> 90 days", value: "₪84K", delta: "+₪11K vs last month", tone: "neg" },
      { label: "Current", value: "₪928K", tone: "pos" },
    ],
  };
  return {
    toolLabel: "Aggregating A/R Invoices",
    answer: {
      text:
        "Your total accounts-receivable balance is **₪1.24M**, of which **₪312K (25%)** is overdue. The **90+ day** bucket grew by ₪11K versus last month — worth a collections follow-up.",
      widget: kpis,
      source: {
        form: "AINVOICES",
        label: "A/R Invoices",
        asOf: nowStamp(),
        odata: "AINVOICES?$filter=PAID eq 'N'&$apply=aggregate(DEBIT with sum as Total)",
      },
    },
  };
}

function overdueInvoices(): EngineResult {
  const widget: Widget = {
    kind: "table",
    title: "Overdue invoices over ₪10,000",
    columns: [
      { key: "inv", label: "Invoice" },
      { key: "cust", label: "Customer" },
      { key: "due", label: "Due" },
      { key: "days", label: "Days late", numeric: true },
      { key: "amt", label: "Amount", numeric: true },
    ],
    rows: [
      { cells: { inv: "IN-24881", cust: "Blue Ridge Mfg", due: "12 May", days: 50, amt: "₪42,300" }, status: { label: "Overdue", tone: "neg" } },
      { cells: { inv: "IN-24790", cust: "Nadel & Sons", due: "28 May", days: 34, amt: "₪28,100" }, status: { label: "Overdue", tone: "neg" } },
      { cells: { inv: "IN-24902", cust: "Tech Solutions Ltd", due: "05 Jun", days: 26, amt: "₪19,750" }, status: { label: "Overdue", tone: "warn" } },
      { cells: { inv: "IN-25010", cust: "Coral Systems", due: "18 Jun", days: 13, amt: "₪13,400" }, status: { label: "Overdue", tone: "warn" } },
    ],
    footnote: "4 invoices · ₪103,550 overdue",
  };
  return {
    toolLabel: "Querying A/R Invoices",
    answer: {
      text:
        "There are **4 overdue invoices above ₪10,000**, totalling **₪103,550**. The oldest is **IN-24881 (Blue Ridge Mfg)** at 50 days past due.",
      widget,
      source: {
        form: "AINVOICES",
        label: "A/R Invoices",
        asOf: nowStamp(),
        odata: "AINVOICES?$filter=PAID eq 'N' and DEBIT gt 10000&$orderby=FNCDATE",
      },
    },
  };
}

function belowReorder(): EngineResult {
  const widget: Widget = {
    kind: "table",
    title: "Parts below reorder point",
    columns: [
      { key: "part", label: "Part" },
      { key: "desc", label: "Description" },
      { key: "onhand", label: "On hand", numeric: true },
      { key: "reorder", label: "Reorder pt", numeric: true },
      { key: "short", label: "Shortfall", numeric: true },
    ],
    rows: [
      { cells: { part: "6801-A", desc: "Bracket, steel", onhand: 12, reorder: 50, short: 38 }, status: { label: "Critical", tone: "neg" } },
      { cells: { part: "4402-C", desc: "Sensor module", onhand: 30, reorder: 40, short: 10 }, status: { label: "Low", tone: "warn" } },
      { cells: { part: "7710-B", desc: "Cable harness", onhand: 5, reorder: 25, short: 20 }, status: { label: "Critical", tone: "neg" } },
    ],
    footnote: "3 parts below reorder point",
  };
  return {
    toolLabel: "Querying Parts / Inventory",
    answer: {
      text:
        "**3 parts** are below their reorder point. **6801-A** and **7710-B** are critical (shortfall of 38 and 20 units). Consider raising purchase orders for these.",
      widget,
      source: {
        form: "LOGPART",
        label: "Parts / Inventory",
        asOf: nowStamp(),
        odata: "LOGPART?$filter=BALANCE lt SAFEQUANT&$orderby=BALANCE",
      },
    },
  };
}

function salesTrend(): EngineResult {
  const chart: Widget = {
    kind: "chart",
    title: "Revenue — last 6 months",
    unit: "₪K",
    bars: [
      { label: "Feb", value: 410 },
      { label: "Mar", value: 468 },
      { label: "Apr", value: 502 },
      { label: "May", value: 486 },
      { label: "Jun", value: 553 },
      { label: "Jul", value: 121 },
    ],
  };
  return {
    toolLabel: "Aggregating Sales Orders",
    answer: {
      text:
        "Revenue has trended **up over the last 6 months**, peaking at **₪553K in June**. July is only partial (month-to-date ₪121K). The 6-month average is about ₪485K.",
      widget: chart,
      source: {
        form: "ORDERS",
        label: "Sales Orders",
        asOf: nowStamp(),
        odata: "ORDERS?$apply=groupby((month),aggregate(QPRICE with sum as Revenue))",
      },
    },
  };
}

function topCustomers(): EngineResult {
  const chart: Widget = {
    kind: "chart",
    title: "Top customers by revenue · this quarter",
    unit: "₪K",
    bars: [
      { label: "Tech Solutions", value: 421 },
      { label: "Blue Ridge", value: 388 },
      { label: "Coral Systems", value: 296 },
      { label: "Nadel & Sons", value: 210 },
      { label: "Orbit Retail", value: 174 },
    ],
  };
  return {
    toolLabel: "Aggregating Sales Orders",
    answer: {
      text:
        "Your **top 5 customers this quarter** are led by **Tech Solutions Ltd (₪421K)** and **Blue Ridge Mfg (₪388K)**. Together the top 5 account for roughly 58% of quarterly revenue.",
      widget: chart,
      source: {
        form: "ORDERS",
        label: "Sales Orders",
        asOf: nowStamp(),
        odata: "ORDERS?$apply=groupby((CUST),aggregate(QPRICE with sum as Rev))&$orderby=Rev desc&$top=5",
      },
    },
  };
}

function fallback(query: string): EngineResult {
  return {
    toolLabel: "Searching Priority",
    answer: {
      text:
        `I can read live data from your Priority environment — orders, customers, invoices and inventory (read-only). ` +
        `I couldn't map *"${query}"* to a demo query yet. Try one of the suggested questions, e.g. **"A/R aging"**, ` +
        `**"open orders for customer 10001"**, or **"parts below reorder point"**.`,
    },
  };
}

// ---- Router ------------------------------------------------------------------

export function runMockEngine(query: string): EngineResult {
  const q = query.toLowerCase();
  const has = (...ks: string[]) => ks.some((k) => q.includes(k));

  if (has("aging", "a/r", "receivable", "ar aging")) return arAging();
  if (has("overdue") || (has("invoice") && has("10,000", "10000", "10k", "over")))
    return overdueInvoices();
  if (has("reorder", "below", "stock", "inventory", "part")) return belowReorder();
  if (has("trend", "last 6", "revenue", "sales trend", "over time")) return salesTrend();
  if (has("top") && has("customer")) return topCustomers();
  if (has("order") && has("open", "10001", "customer", "this month")) return openOrders();
  if (has("customer") && has("10001", "overview", "detail", "profile")) return customerOverview();
  if (has("order")) return openOrders();
  if (has("customer")) return customerOverview();
  if (has("invoice")) return overdueInvoices();

  return fallback(query);
}
