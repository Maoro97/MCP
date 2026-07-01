import { Database } from "lucide-react";
import type { Source } from "@/lib/types";

/**
 * Provenance chip shown under an answer: which Priority form + when.
 * The OData query is exposed on hover — trust matters for ERP answers.
 */
export function SourceChip({ source }: { source: Source }) {
  return (
    <div
      className="group inline-flex items-center gap-1.5 rounded-full border border-[color:var(--border)] bg-[color:var(--surface-2)] px-2.5 py-1 text-xs text-[color:var(--muted)]"
      title={source.odata ? `OData · ${source.odata}` : undefined}
    >
      <Database size={12} className="text-[color:var(--accent)]" />
      <span className="font-medium text-[color:var(--text)]">{source.label}</span>
      <span className="text-[color:var(--faint)]">·</span>
      <span className="font-mono">{source.form}</span>
      <span className="text-[color:var(--faint)]">·</span>
      <span>as of {source.asOf}</span>
    </div>
  );
}
