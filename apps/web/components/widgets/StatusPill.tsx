import type { StatusTone } from "@/lib/types";
import { toneClasses } from "./tone";

export function StatusPill({
  label,
  tone,
}: {
  label: string;
  tone: StatusTone;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${toneClasses(
        tone
      )}`}
    >
      {label}
    </span>
  );
}
