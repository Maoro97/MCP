"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Plus, X } from "lucide-react";
import { useStore, useToast } from "@/lib/store";
import { lastPerformance, workoutVolumeKg } from "@/lib/calc";
import { fmtElapsed, kgToUnit, round1, unitToKg } from "@/lib/format";
import { MUSCLE_GROUPS, uid, type Workout, type WorkoutSet } from "@/lib/types";
import { Stepper } from "@/components/Stepper";
import { Sheet } from "@/components/Sheet";

export default function ActiveWorkoutPage() {
  const { db, update } = useStore();
  const toast = useToast();
  const router = useRouter();
  const workout = db.workouts.find((w) => w.id === db.activeWorkoutId);
  const [now, setNow] = useState(Date.now());
  const [pickerOpen, setPickerOpen] = useState(false);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (!workout) router.replace("/train");
  }, [workout, router]);

  if (!workout) return null;

  const finish = () => {
    update((d) => ({
      ...d,
      workouts: d.workouts.map((w) =>
        w.id === workout.id ? { ...w, finishedAt: Date.now() } : w
      ),
      activeWorkoutId: undefined,
    }));
    toast.show(
      `${workout.name} done — ${workout.sets.length} sets, ${Math.round(
        kgToUnit(workoutVolumeKg(workout.sets), db.settings.unitWeight)
      )} ${db.settings.unitWeight} volume`
    );
    router.push("/train");
  };

  const discard = () => {
    if (!window.confirm("Discard this workout and all its sets?")) return;
    update((d) => ({
      ...d,
      workouts: d.workouts.filter((w) => w.id !== workout.id),
      activeWorkoutId: undefined,
    }));
    router.push("/train");
  };

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold">{workout.name}</h1>
          <p className="tnum text-sm" style={{ color: "var(--color-train)" }}>
            {fmtElapsed(now - workout.startedAt)}
          </p>
        </div>
        <button onClick={discard} className="text-sm text-faint">
          Discard
        </button>
      </header>

      {workout.exerciseOrder.length === 0 && (
        <p className="rounded-[16px] border border-dashed border-line p-6 text-center text-sm text-faint">
          Empty workout — add your first exercise below.
        </p>
      )}

      {workout.exerciseOrder.map((exId) => (
        <ExerciseCard key={exId} workout={workout} exerciseId={exId} />
      ))}

      <button
        onClick={() => setPickerOpen(true)}
        className="flex w-full items-center justify-center gap-1 rounded-[16px] border border-dashed border-line py-3 text-sm text-muted"
      >
        <Plus size={16} /> Add exercise
      </button>

      <button
        onClick={finish}
        className="flex h-12 w-full items-center justify-center gap-2 rounded-2xl font-semibold text-white active:opacity-80"
        style={{ background: "var(--color-train)" }}
      >
        <Check size={18} /> Finish workout
      </button>

      <Sheet open={pickerOpen} onClose={() => setPickerOpen(false)} title="Add exercise">
        <div className="max-h-[60dvh] space-y-3 overflow-y-auto">
          {MUSCLE_GROUPS.map((g) => {
            const group = db.exercises.filter(
              (e) => !e.archived && e.muscleGroup === g && !workout.exerciseOrder.includes(e.id)
            );
            if (!group.length) return null;
            return (
              <div key={g}>
                <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-faint">{g}</p>
                <div className="flex flex-wrap gap-2">
                  {group.map((e) => (
                    <button
                      key={e.id}
                      onClick={() => {
                        update((d) => ({
                          ...d,
                          workouts: d.workouts.map((w) =>
                            w.id === workout.id
                              ? { ...w, exerciseOrder: [...w.exerciseOrder, e.id] }
                              : w
                          ),
                        }));
                        setPickerOpen(false);
                      }}
                      className="rounded-full border border-line bg-surface2 px-3 py-2 text-sm"
                    >
                      {e.name}
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </Sheet>
    </div>
  );
}

function ExerciseCard({ workout, exerciseId }: { workout: Workout; exerciseId: string }) {
  const { db, update } = useStore();
  const unit = db.settings.unitWeight;
  const exercise = db.exercises.find((e) => e.id === exerciseId);
  const routine = workout.routineId
    ? db.routines.find((r) => r.id === workout.routineId)
    : undefined;
  const targetSets = routine?.exercises.find((e) => e.exerciseId === exerciseId)?.targetSets;

  const sets = workout.sets
    .filter((s) => s.exerciseId === exerciseId)
    .sort((a, b) => a.setNumber - b.setNumber);
  const last = useMemo(
    () => lastPerformance(db, exerciseId, workout.id),
    [db, exerciseId, workout.id]
  );

  // Pre-fill: last set this session → matching set from last time → last time's
  // final set → a sensible default. One tap logs a repeat.
  const prefill = (): { w: number; r: number } => {
    const prev = sets[sets.length - 1];
    if (prev) return { w: kgToUnit(prev.weightKg, unit), r: prev.reps };
    const fromLast = last?.[sets.length] ?? last?.[last.length - 1];
    if (fromLast) return { w: kgToUnit(fromLast.weightKg, unit), r: fromLast.reps };
    return { w: 20, r: 8 };
  };
  const init = prefill();
  const [weight, setWeight] = useState(round1(init.w));
  const [reps, setReps] = useState(init.r);

  const logSet = () => {
    const set: WorkoutSet = {
      id: uid(),
      exerciseId,
      setNumber: sets.length + 1,
      weightKg: round1(unitToKg(weight, unit)),
      reps,
      loggedAt: Date.now(),
    };
    update((d) => ({
      ...d,
      workouts: d.workouts.map((w) =>
        w.id === workout.id ? { ...w, sets: [...w.sets, set] } : w
      ),
    }));
  };

  const removeSet = (id: string) => {
    update((d) => ({
      ...d,
      workouts: d.workouts.map((w) => {
        if (w.id !== workout.id) return w;
        const kept = w.sets.filter((s) => s.id !== id);
        let n = 0;
        return {
          ...w,
          sets: kept.map((s) =>
            s.exerciseId === exerciseId ? { ...s, setNumber: ++n } : s
          ),
        };
      }),
    }));
  };

  const removeExercise = () => {
    if (sets.length && !window.confirm(`Remove ${exercise?.name} and its ${sets.length} logged sets?`))
      return;
    update((d) => ({
      ...d,
      workouts: d.workouts.map((w) =>
        w.id === workout.id
          ? {
              ...w,
              exerciseOrder: w.exerciseOrder.filter((x) => x !== exerciseId),
              sets: w.sets.filter((s) => s.exerciseId !== exerciseId),
            }
          : w
      ),
    }));
  };

  return (
    <section className="rounded-[16px] border border-line bg-surface p-4">
      <div className="mb-1 flex items-center justify-between">
        <h2 className="font-semibold">{exercise?.name ?? "Exercise"}</h2>
        <div className="flex items-center gap-2">
          {targetSets && (
            <span className="tnum text-xs text-muted">
              {Math.min(sets.length, targetSets)}/{targetSets} sets
            </span>
          )}
          <button aria-label="Remove exercise" onClick={removeExercise} className="p-1 text-faint">
            <X size={15} />
          </button>
        </div>
      </div>

      <p className="tnum mb-2 rounded-lg bg-surface2 px-2 py-1 text-xs text-muted">
        {last
          ? `Last time: ${last
              .map((s) => `${round1(kgToUnit(s.weightKg, unit))}×${s.reps}`)
              .join(", ")}`
          : "First time — set your baseline"}
      </p>

      {sets.length > 0 && (
        <ul className="mb-2 space-y-1">
          {sets.map((s) => (
            <li key={s.id} className="flex items-center gap-2 text-sm">
              <Check size={14} style={{ color: "var(--color-train)" }} />
              <span className="w-10 text-faint">Set {s.setNumber}</span>
              <span className="tnum flex-1">
                {round1(kgToUnit(s.weightKg, unit))} {unit} × {s.reps}
              </span>
              <button aria-label="Remove set" onClick={() => removeSet(s.id)} className="p-1 text-faint">
                <X size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="space-y-2">
        <div className="flex items-end justify-center gap-5">
          <Stepper label={unit} value={weight} onChange={setWeight} step={2.5} min={0} />
          <Stepper label="reps" value={reps} onChange={setReps} step={1} min={1} />
        </div>
        <button
          onClick={logSet}
          className="h-11 w-full rounded-xl font-semibold text-white active:opacity-80"
          style={{ background: "var(--color-train)" }}
        >
          Log set
        </button>
      </div>
    </section>
  );
}
