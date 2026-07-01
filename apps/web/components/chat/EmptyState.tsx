import { Sparkles, ArrowRight } from "lucide-react";
import { ROLE_PROMPTS } from "@/lib/mock";

/** Landing view: brand blurb + role-grouped starter questions. */
export function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center px-4 py-10 text-center">
      <div className="mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-[color:var(--accent-soft)] text-[color:var(--accent)]">
        <Sparkles size={26} />
      </div>
      <h1 className="text-2xl font-semibold tracking-tight">
        Ask your Priority ERP
      </h1>
      <p className="mt-2 max-w-md text-sm text-[color:var(--muted)]">
        Read-only, natural-language answers about orders, customers, invoices and
        inventory — with the exact source shown on every result.
      </p>

      <div className="mt-8 w-full space-y-4 text-start">
        {ROLE_PROMPTS.map((group) => (
          <div key={group.role}>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-[color:var(--faint)]">
              {group.role}
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {group.prompts.map((p) => (
                <button
                  key={p}
                  onClick={() => onPick(p)}
                  className="group flex items-center justify-between gap-2 rounded-xl border border-[color:var(--border)] bg-[color:var(--surface)] px-3.5 py-3 text-start text-sm transition-colors hover:border-[color:var(--accent)] hover:bg-[color:var(--surface-2)]"
                >
                  <span>{p}</span>
                  <ArrowRight
                    size={15}
                    className="shrink-0 text-[color:var(--faint)] transition-transform group-hover:translate-x-0.5 group-hover:text-[color:var(--accent)] rtl:rotate-180"
                  />
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
