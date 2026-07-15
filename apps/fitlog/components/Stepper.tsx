"use client";

import { Minus, Plus } from "lucide-react";

/** −/+ stepper with direct numeric entry. Big touch targets for gym use. */
export function Stepper({
  value,
  onChange,
  step = 1,
  min = 0,
  label,
}: {
  value: number;
  onChange: (v: number) => void;
  step?: number;
  min?: number;
  label: string;
}) {
  const set = (v: number) => onChange(Math.max(min, Math.round(v * 100) / 100));
  return (
    <div className="flex flex-col items-center gap-1">
      <span className="text-[11px] uppercase tracking-wide text-faint">{label}</span>
      <div className="flex items-center gap-1">
        <button
          aria-label={`Decrease ${label}`}
          onClick={() => set(value - step)}
          className="flex h-11 w-11 items-center justify-center rounded-xl bg-surface2 text-muted active:bg-line"
        >
          <Minus size={18} />
        </button>
        <input
          aria-label={label}
          inputMode="decimal"
          className="tnum h-11 w-16 rounded-xl bg-surface2 text-center text-lg font-semibold"
          value={String(value)}
          onChange={(e) => {
            const v = parseFloat(e.target.value);
            if (!Number.isNaN(v)) set(v);
            else if (e.target.value === "") set(min);
          }}
        />
        <button
          aria-label={`Increase ${label}`}
          onClick={() => set(value + step)}
          className="flex h-11 w-11 items-center justify-center rounded-xl bg-surface2 text-muted active:bg-line"
        >
          <Plus size={18} />
        </button>
      </div>
    </div>
  );
}
