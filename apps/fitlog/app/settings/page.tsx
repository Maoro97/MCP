"use client";

import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { useStore, useToast } from "@/lib/store";
import { kgToUnit, round1, unitToKg } from "@/lib/format";
import { seedDB } from "@/lib/seed";

const card = "rounded-[16px] border border-line bg-surface p-4";

export default function SettingsPage() {
  const { db, update } = useStore();
  const toast = useToast();
  const unit = db.settings.unitWeight;

  const setGoal = (key: "kcal" | "protein" | "carbs" | "fat" | "waterMl", raw: string) => {
    const v = parseInt(raw, 10);
    if (Number.isNaN(v) || v < 0) return;
    update((d) => ({ ...d, goals: { ...d.goals, [key]: v } }));
  };

  const exportData = () => {
    const blob = new Blob([JSON.stringify(db, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `fitlog-export-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.show("Exported all data as JSON");
  };

  const resetAll = () => {
    if (!window.confirm("Delete ALL logged data and restore defaults? This cannot be undone."))
      return;
    update(() => seedDB());
    toast.show("All data reset");
  };

  const field =
    "tnum h-11 w-24 rounded-xl bg-surface2 px-3 text-right";

  const goalRows: { key: "kcal" | "protein" | "carbs" | "fat" | "waterMl"; label: string; unit: string }[] = [
    { key: "kcal", label: "Calories", unit: "kcal" },
    { key: "protein", label: "Protein", unit: "g" },
    { key: "carbs", label: "Carbs", unit: "g" },
    { key: "fat", label: "Fat", unit: "g" },
    { key: "waterMl", label: "Water", unit: "ml" },
  ];

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-2">
        <Link href="/" aria-label="Back" className="rounded-full bg-surface p-2 text-muted">
          <ChevronLeft size={20} />
        </Link>
        <h1 className="text-xl font-bold">Settings</h1>
      </header>

      <section className={card}>
        <h2 className="mb-3 font-semibold">Daily goals</h2>
        <div className="space-y-2">
          {goalRows.map(({ key, label, unit: u }) => (
            <label key={key} className="flex items-center justify-between">
              <span className="text-sm text-muted">{label}</span>
              <span className="flex items-center gap-2">
                <input
                  inputMode="numeric"
                  value={String(db.goals[key] ?? 0)}
                  onChange={(e) => setGoal(key, e.target.value)}
                  className={field}
                />
                <span className="w-8 text-sm text-faint">{u}</span>
              </span>
            </label>
          ))}
          <label className="flex items-center justify-between">
            <span className="text-sm text-muted">Target weight</span>
            <span className="flex items-center gap-2">
              <input
                inputMode="decimal"
                value={
                  db.goals.targetWeightKg != null
                    ? String(round1(kgToUnit(db.goals.targetWeightKg, unit)))
                    : ""
                }
                placeholder="—"
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  update((d) => ({
                    ...d,
                    goals: {
                      ...d.goals,
                      targetWeightKg: Number.isNaN(v) ? undefined : round1(unitToKg(v, unit)),
                    },
                  }));
                }}
                className={field}
              />
              <span className="w-8 text-sm text-faint">{unit}</span>
            </span>
          </label>
        </div>
      </section>

      <section className={card}>
        <h2 className="mb-3 font-semibold">Units</h2>
        <div className="flex gap-2">
          {(["kg", "lb"] as const).map((u) => (
            <button
              key={u}
              onClick={() => update((d) => ({ ...d, settings: { ...d.settings, unitWeight: u } }))}
              className={`h-11 flex-1 rounded-xl text-sm font-semibold ${
                unit === u ? "bg-ink text-bg" : "bg-surface2 text-muted"
              }`}
            >
              {u === "kg" ? "Kilograms (kg)" : "Pounds (lb)"}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-faint">
          Data is always stored in kg — switching units only changes the display.
        </p>
      </section>

      <section className={card}>
        <h2 className="mb-3 font-semibold">Data</h2>
        <button
          onClick={exportData}
          className="mb-2 h-11 w-full rounded-xl bg-surface2 text-sm font-medium"
        >
          Export all data (JSON)
        </button>
        <button
          onClick={resetAll}
          className="h-11 w-full rounded-xl bg-surface2 text-sm font-medium text-danger"
        >
          Reset all data
        </button>
        <p className="mt-2 text-xs text-faint">
          FitLog currently stores everything on this device (localStorage). Cloud sync via
          Supabase is the next roadmap phase — the schema is ready in supabase/migrations.
        </p>
      </section>
    </div>
  );
}
