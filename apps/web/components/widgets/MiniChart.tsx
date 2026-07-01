import type { ChartWidget } from "@/lib/types";

/** Lightweight hand-rolled vertical bar chart (no charting dependency). */
export function MiniChart({ widget }: { widget: ChartWidget }) {
  const max = Math.max(...widget.bars.map((b) => b.value), 1);

  return (
    <div className="rounded-[var(--radius-app)] border border-[color:var(--border)] bg-[color:var(--surface)] p-4">
      <div className="mb-4 flex items-baseline justify-between">
        <div className="text-sm font-semibold">{widget.title}</div>
        {widget.unit && (
          <div className="text-xs text-[color:var(--faint)]">{widget.unit}</div>
        )}
      </div>
      <div className="flex h-44 items-stretch gap-3">
        {widget.bars.map((b, i) => {
          const pct = Math.max((b.value / max) * 100, 2);
          return (
            <div key={i} className="flex flex-1 flex-col items-center gap-2">
              <div className="flex w-full flex-1 flex-col items-center justify-end gap-1">
                <div className="text-xs font-medium tabular-nums text-[color:var(--muted)]">
                  {b.value}
                </div>
                <div
                  className="w-full rounded-t-md bg-[color:var(--accent)] transition-all duration-500"
                  style={{ height: `${pct}%` }}
                  title={`${b.label}: ${b.value}`}
                />
              </div>
              <div className="w-full truncate text-center text-xs text-[color:var(--faint)]">
                {b.label}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
