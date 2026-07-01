import { Loader2 } from "lucide-react";

/** Shown while the assistant is "calling a tool" (querying Priority). */
export function ToolIndicator({ label }: { label: string }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-[color:var(--border)] bg-[color:var(--surface-2)] px-3 py-1.5 text-xs text-[color:var(--muted)]">
      <Loader2 size={13} className="animate-spin text-[color:var(--accent)]" />
      <span>{label}</span>
      <span className="ms-0.5 flex gap-0.5">
        <span className="dot h-1 w-1 rounded-full bg-[color:var(--muted)]" style={{ animationDelay: "0ms" }} />
        <span className="dot h-1 w-1 rounded-full bg-[color:var(--muted)]" style={{ animationDelay: "160ms" }} />
        <span className="dot h-1 w-1 rounded-full bg-[color:var(--muted)]" style={{ animationDelay: "320ms" }} />
      </span>
    </div>
  );
}
