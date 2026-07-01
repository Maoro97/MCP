import type { StatusTone } from "@/lib/types";

/** Map a semantic tone to background/text colors used by pills and deltas. */
export function toneClasses(tone: StatusTone | undefined): string {
  switch (tone) {
    case "pos":
      return "bg-[color:var(--pos)]/12 text-[color:var(--pos)]";
    case "warn":
      return "bg-[color:var(--warn)]/12 text-[color:var(--warn)]";
    case "neg":
      return "bg-[color:var(--neg)]/12 text-[color:var(--neg)]";
    default:
      return "bg-[color:var(--surface-2)] text-[color:var(--muted)]";
  }
}
