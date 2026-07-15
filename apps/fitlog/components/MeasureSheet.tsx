"use client";

import { useState } from "react";
import { Sheet } from "./Sheet";
import { useStore, useToast } from "@/lib/store";
import { todayStr } from "@/lib/format";
import { METRICS, uid, type MetricKey } from "@/lib/types";

/** Bi-weekly measurement session — previous values shown as placeholders. */
export function MeasureSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { db, update } = useStore();
  const toast = useToast();
  const last = [...db.measurements].sort((a, b) => b.loggedAt - a.loggedAt)[0];
  const [vals, setVals] = useState<Partial<Record<MetricKey, string>>>({});

  const save = () => {
    const values: Partial<Record<MetricKey, number>> = {};
    let any = false;
    for (const { key } of METRICS) {
      const v = parseFloat(vals[key] ?? "");
      if (!Number.isNaN(v) && v > 0) {
        values[key] = v;
        any = true;
      }
    }
    if (!any) return;
    update((d) => ({
      ...d,
      measurements: [
        ...d.measurements,
        { id: uid(), date: todayStr(), loggedAt: Date.now(), values },
      ],
    }));
    toast.show("Measurements saved");
    setVals({});
    onClose();
  };

  return (
    <Sheet open={open} onClose={onClose} title="Body measurements">
      <div className="grid grid-cols-2 gap-3">
        {METRICS.map(({ key, label }) => (
          <label key={key} className="block">
            <span className="mb-1 block text-sm text-muted">{label}</span>
            <div className="flex items-center gap-2 rounded-xl bg-surface2 px-3">
              <input
                inputMode="decimal"
                placeholder={last?.values[key] != null ? String(last.values[key]) : "—"}
                value={vals[key] ?? ""}
                onChange={(e) => setVals((v) => ({ ...v, [key]: e.target.value }))}
                className="tnum h-11 w-full bg-transparent text-lg"
              />
              <span className="text-sm text-faint">cm</span>
            </div>
          </label>
        ))}
      </div>
      <p className="mt-3 text-sm text-faint">
        Leave a field empty to skip it. Placeholders show your last session.
      </p>
      <button
        onClick={save}
        className="mt-4 h-12 w-full rounded-2xl bg-accent font-semibold text-white active:opacity-80"
      >
        Save session
      </button>
    </Sheet>
  );
}
