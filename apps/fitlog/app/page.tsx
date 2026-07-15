"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Droplets, Dumbbell, Play, Scale, Settings } from "lucide-react";
import { useStore, useToast } from "@/lib/store";
import { dayTotals, dayWaterMl, latestWeight, nextRoutine, weeklyDeltaKg } from "@/lib/calc";
import { fmtDay, fmtWeight, round1, todayStr } from "@/lib/format";
import { uid } from "@/lib/types";
import { Ring } from "@/components/Ring";
import { MacroBar } from "@/components/MacroBar";
import { WeightSheet } from "@/components/WeightSheet";

export default function TodayPage() {
  const { db, update } = useStore();
  const toast = useToast();
  const router = useRouter();
  const [weightOpen, setWeightOpen] = useState(false);

  const date = todayStr();
  const totals = dayTotals(db, date);
  const goals = db.goals;
  const waterMl = dayWaterMl(db, date);
  const cups = Math.max(1, Math.round(goals.waterMl / 250));
  const filled = Math.min(cups, Math.floor(waterMl / 250));
  const weight = latestWeight(db);
  const delta = weeklyDeltaKg(db, date);
  const unit = db.settings.unitWeight;
  const suggestion = nextRoutine(db);
  const remaining = Math.max(0, Math.round(goals.kcal - totals.kcal));

  const addWater = () => {
    const entry = { id: uid(), date, loggedAt: Date.now(), amountMl: 250 };
    update((d) => ({ ...d, water: [...d.water, entry] }));
  };
  const removeWater = () => {
    update((d) => {
      const today = d.water.filter((w) => w.date === date);
      const last = today[today.length - 1];
      return last ? { ...d, water: d.water.filter((w) => w.id !== last.id) } : d;
    });
  };

  const startWorkout = () => {
    if (db.activeWorkoutId) {
      router.push("/train/active");
      return;
    }
    if (!suggestion) {
      router.push("/train");
      return;
    }
    const id = uid();
    update((d) => ({
      ...d,
      workouts: [
        ...d.workouts,
        {
          id,
          routineId: suggestion.id,
          name: suggestion.name,
          startedAt: Date.now(),
          exerciseOrder: suggestion.exercises.map((e) => e.exerciseId),
          sets: [],
        },
      ],
      activeWorkoutId: id,
    }));
    toast.show(`Started ${suggestion.name}`);
    router.push("/train/active");
  };

  const card = "rounded-[16px] border border-line bg-surface p-4";

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">{fmtDay(date)}</h1>
          <p className="text-sm text-faint">FitLog</p>
        </div>
        <Link href="/settings" aria-label="Settings" className="rounded-full bg-surface p-2.5 text-muted">
          <Settings size={20} />
        </Link>
      </header>

      {/* Calories + macros */}
      <section className={card}>
        <div className="flex flex-col items-center">
          <Ring value={totals.kcal} goal={goals.kcal} color="var(--color-cal)">
            <span className="tnum text-4xl font-bold">{Math.round(totals.kcal)}</span>
            <span className="text-sm text-faint">of {goals.kcal} kcal</span>
          </Ring>
          <p className="mt-2 text-sm text-muted">
            <span className="tnum font-semibold text-ink">{remaining}</span> kcal remaining
          </p>
        </div>
        <div className="mt-4 space-y-3">
          <MacroBar label="Protein" value={totals.protein} goal={goals.protein} color="var(--color-protein)" />
          <MacroBar label="Carbs" value={totals.carbs} goal={goals.carbs} color="var(--color-carbs)" />
          <MacroBar label="Fat" value={totals.fat} goal={goals.fat} color="var(--color-fat)" />
        </div>
      </section>

      {/* Water */}
      <section className={card}>
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Droplets size={18} className="text-water" />
            <span className="font-semibold">Water</span>
          </div>
          <span className="tnum text-sm text-muted">
            {(waterMl / 1000).toFixed(2).replace(/\.?0+$/, "") || "0"} / {(goals.waterMl / 1000).toFixed(1)} L
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          {Array.from({ length: cups }, (_, i) => (
            <button
              key={i}
              aria-label={i < filled ? "Remove 250 ml" : "Add 250 ml"}
              onClick={i < filled ? removeWater : addWater}
              className="h-9 w-9 rounded-full border transition-colors"
              style={
                i < filled
                  ? { background: "var(--color-water)", borderColor: "var(--color-water)" }
                  : { background: "var(--color-surface2)", borderColor: "var(--color-line)" }
              }
            />
          ))}
        </div>
        <p className="mt-2 text-xs text-faint">Tap a cup to add 250 ml · tap a filled cup to undo</p>
      </section>

      {/* Weight */}
      <button onClick={() => setWeightOpen(true)} className={`${card} block w-full text-left`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Scale size={18} className="text-muted" />
            <span className="font-semibold">Weight</span>
          </div>
          {weight ? (
            <div className="text-right">
              <div className="tnum text-lg font-bold">{fmtWeight(weight.weightKg, unit)}</div>
              {delta !== undefined && (
                <div className="tnum text-xs text-muted">
                  {delta <= 0 ? "▼" : "▲"} {Math.abs(round1(delta))} kg vs last week
                </div>
              )}
            </div>
          ) : (
            <span className="text-sm text-accent">Log your first weigh-in</span>
          )}
        </div>
      </button>

      {/* Workout */}
      <section className={card}>
        <div className="mb-3 flex items-center gap-2">
          <Dumbbell size={18} className="text-train" />
          <span className="font-semibold">Training</span>
        </div>
        <button
          onClick={startWorkout}
          className="flex h-12 w-full items-center justify-center gap-2 rounded-2xl font-semibold text-white active:opacity-80"
          style={{ background: "var(--color-train)" }}
        >
          <Play size={18} />
          {db.activeWorkoutId
            ? "Resume workout"
            : suggestion
              ? `Start ${suggestion.name}`
              : "Set up a routine"}
        </button>
      </section>

      <WeightSheet open={weightOpen} onClose={() => setWeightOpen(false)} />
    </div>
  );
}
