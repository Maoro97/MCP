/*
 * Result-shape contract shared by the (mock) assistant engine and the GUI widgets.
 *
 * In Phase B/C these same shapes are what the MCP tools + chat backend will emit,
 * so the "generative UI" rendering layer stays unchanged when real Priority data
 * replaces the fixtures. This file is the seed of `packages/shared`.
 */

export type Role = "user" | "assistant";

export type StatusTone = "pos" | "warn" | "neg" | "muted";

/** A chip describing where an answer's data came from in Priority. */
export interface Source {
  /** Priority form / OData entity name, e.g. "ORDERS". */
  form: string;
  /** Human label, e.g. "Sales Orders". */
  label: string;
  /** When the data was read. */
  asOf: string;
  /** The OData query that (will) back this answer — shown on hover for trust. */
  odata?: string;
}

export type Cell = string | number;

export interface TableColumn {
  key: string;
  label: string;
  /** Right-align numeric/currency columns. */
  numeric?: boolean;
}

export interface TableRow {
  cells: Record<string, Cell>;
  /** Optional per-row status pill shown in a "status" column. */
  status?: { label: string; tone: StatusTone };
}

export interface TableWidget {
  kind: "table";
  title: string;
  columns: TableColumn[];
  rows: TableRow[];
  /** e.g. "42 rows · showing 8" */
  footnote?: string;
}

export interface RecordField {
  label: string;
  value: string;
  emphasize?: boolean;
}

export interface RecordWidget {
  kind: "record";
  title: string;
  subtitle?: string;
  status?: { label: string; tone: StatusTone };
  fields: RecordField[];
}

export interface KpiTile {
  label: string;
  value: string;
  /** e.g. "+12% vs last month" */
  delta?: string;
  tone?: StatusTone;
}

export interface KpiWidget {
  kind: "kpis";
  tiles: KpiTile[];
}

export interface ChartBar {
  label: string;
  value: number;
}

export interface ChartWidget {
  kind: "chart";
  title: string;
  unit?: string;
  bars: ChartBar[];
}

export type Widget = TableWidget | RecordWidget | KpiWidget | ChartWidget;

/** A full assistant answer: prose + an optional rich widget + a source chip. */
export interface AssistantAnswer {
  text: string;
  widget?: Widget;
  source?: Source;
}

export interface ChatMessage {
  id: string;
  role: Role;
  /** For user messages: the raw text. For assistant: the streamed prose. */
  text: string;
  widget?: Widget;
  source?: Source;
  /** True while the assistant answer is still streaming in. */
  streaming?: boolean;
  /** Label shown in the tool-call indicator, e.g. "Querying Sales Orders…". */
  toolLabel?: string;
}
