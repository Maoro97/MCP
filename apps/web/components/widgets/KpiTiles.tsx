import type { KpiWidget } from "@/lib/types";
import { toneClasses } from "./tone";

/** Row of KPI tiles for aggregate answers. */
export function KpiTiles({ widget }: { widget: KpiWidget }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {widget.tiles.map((t, i) => (
        <div
          key={i}
          className="rounded-[var(--radius-app)] border border-[color:var(--border)] bg-[color:var(--surface)] p-3.5"
        >
          <div className="text-xs font-medium uppercase tracking-wide text-[color:var(--faint)]">
            {t.label}
          </div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-[color:var(--text)]">
            {t.value}
          </div>
          {t.delta && (
            <div
              className={`mt-1.5 inline-flex rounded-full px-1.5 py-0.5 text-xs font-medium ${toneClasses(
                t.tone
              )}`}
            >
              {t.delta}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
