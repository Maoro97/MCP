"use client";

/** Thin labeled progress bar — text wears text tokens, only the mark is colored. */
export function MacroBar({
  label,
  value,
  goal,
  color,
  unit = "g",
}: {
  label: string;
  value: number;
  goal: number;
  color: string;
  unit?: string;
}) {
  const frac = goal > 0 ? Math.min(value / goal, 1) : 0;
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-sm">
        <span className="text-muted">{label}</span>
        <span className="tnum">
          {Math.round(value)}
          <span className="text-faint"> / {goal} {unit}</span>
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-surface2">
        <div
          className="h-full rounded-full transition-[width] duration-300"
          style={{ width: `${frac * 100}%`, background: color }}
        />
      </div>
    </div>
  );
}
