import type { RecordWidget } from "@/lib/types";
import { StatusPill } from "./StatusPill";

/** Single-record detail card (customer / order overview). */
export function RecordCard({ widget }: { widget: RecordWidget }) {
  return (
    <div className="rounded-[var(--radius-app)] border border-[color:var(--border)] bg-[color:var(--surface)] p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="text-base font-semibold">{widget.title}</div>
          {widget.subtitle && (
            <div className="text-sm text-[color:var(--muted)]">
              {widget.subtitle}
            </div>
          )}
        </div>
        {widget.status && (
          <StatusPill label={widget.status.label} tone={widget.status.tone} />
        )}
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
        {widget.fields.map((f, i) => (
          <div key={i}>
            <div className="text-xs uppercase tracking-wide text-[color:var(--faint)]">
              {f.label}
            </div>
            <div
              className={`mt-0.5 ${
                f.emphasize
                  ? "text-lg font-semibold text-[color:var(--text)]"
                  : "text-sm text-[color:var(--text)]"
              }`}
            >
              {f.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
