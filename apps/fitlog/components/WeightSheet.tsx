"use client";

import { useState } from "react";
import { Sheet } from "./Sheet";
import { useStore, useToast } from "@/lib/store";
import { latestWeight } from "@/lib/calc";
import { kgToUnit, round1, todayStr, unitToKg } from "@/lib/format";
import { uid } from "@/lib/types";

/** Upserts today's weigh-in (one per day, mirrors the DB unique index). */
export function WeightSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { db, update } = useStore();
  const toast = useToast();
  const unit = db.settings.unitWeight;
  const last = latestWeight(db);
  const [val, setVal] = useState(() =>
    last ? String(round1(kgToUnit(last.weightKg, unit))) : ""
  );

  const save = () => {
    const v = parseFloat(val);
    if (Number.isNaN(v) || v <= 0) return;
    const date = todayStr();
    const kg = round1(unitToKg(v, unit));
    update((d) => ({
      ...d,
      weights: [
        ...d.weights.filter((w) => w.date !== date),
        { id: uid(), date, loggedAt: Date.now(), weightKg: kg },
      ],
    }));
    toast.show(`Logged ${v} ${unit}`);
    onClose();
  };

  return (
    <Sheet open={open} onClose={onClose} title="Log weight">
      <div className="flex items-end gap-2">
        <input
          autoFocus
          inputMode="decimal"
          placeholder={last ? String(round1(kgToUnit(last.weightKg, unit))) : "0.0"}
          value={val}
          onChange={(e) => setVal(e.target.value)}
          className="tnum h-14 flex-1 rounded-2xl bg-surface2 px-4 text-center text-3xl font-bold"
        />
        <span className="pb-3 text-lg text-muted">{unit}</span>
      </div>
      <p className="mt-2 text-sm text-faint">
        Saved for today — logging again today replaces it.
      </p>
      <button
        onClick={save}
        className="mt-4 h-12 w-full rounded-2xl bg-accent font-semibold text-white active:opacity-80"
      >
        Save
      </button>
    </Sheet>
  );
}
