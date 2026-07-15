"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Minus, Pencil, Play, Plus, X } from "lucide-react";
import { useStore, useToast } from "@/lib/store";
import { workoutVolumeKg } from "@/lib/calc";
import { fmtShort, fmtWeight, todayStr } from "@/lib/format";
import {
  MUSCLE_GROUPS,
  uid,
  type Exercise,
  type MuscleGroup,
  type Routine,
} from "@/lib/types";
import { Sheet } from "@/components/Sheet";

const card = "rounded-[16px] border border-line bg-surface p-4";

export default function TrainPage() {
  const { db, update } = useStore();
  const toast = useToast();
  const router = useRouter();
  const [routineSheet, setRoutineSheet] = useState<{ open: boolean; routine?: Routine }>({
    open: false,
  });
  const [exerciseSheet, setExerciseSheet] = useState<{ open: boolean; exercise?: Exercise }>({
    open: false,
  });
  const [groupFilter, setGroupFilter] = useState<MuscleGroup | "all">("all");

  const exercises = db.exercises.filter((e) => !e.archived);
  const exName = useMemo(() => new Map(db.exercises.map((e) => [e.id, e.name])), [db.exercises]);
  const routines = db.routines.filter((r) => !r.archived);
  const history = [...db.workouts]
    .filter((w) => w.finishedAt)
    .sort((a, b) => b.startedAt - a.startedAt)
    .slice(0, 5);

  const startWorkout = (routine?: Routine) => {
    const id = uid();
    update((d) => ({
      ...d,
      workouts: [
        ...d.workouts,
        {
          id,
          routineId: routine?.id,
          name: routine?.name ?? "Workout",
          startedAt: Date.now(),
          exerciseOrder: routine ? routine.exercises.map((e) => e.exerciseId) : [],
          sets: [],
        },
      ],
      activeWorkoutId: id,
    }));
    router.push("/train/active");
  };

  const archiveRoutine = (r: Routine) => {
    update((d) => ({
      ...d,
      routines: d.routines.map((x) => (x.id === r.id ? { ...x, archived: true } : x)),
    }));
    toast.show(`Deleted ${r.name}`, () =>
      update((d) => ({
        ...d,
        routines: d.routines.map((x) => (x.id === r.id ? { ...x, archived: false } : x)),
      }))
    );
  };

  const archiveExercise = (e: Exercise) => {
    update((d) => ({
      ...d,
      exercises: d.exercises.map((x) => (x.id === e.id ? { ...x, archived: true } : x)),
    }));
    toast.show(`Deleted ${e.name}`, () =>
      update((d) => ({
        ...d,
        exercises: d.exercises.map((x) => (x.id === e.id ? { ...x, archived: false } : x)),
      }))
    );
  };

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Train</h1>

      {db.activeWorkoutId && (
        <button
          onClick={() => router.push("/train/active")}
          className="flex h-12 w-full items-center justify-center gap-2 rounded-2xl font-semibold text-white active:opacity-80"
          style={{ background: "var(--color-train)" }}
        >
          <Play size={18} /> Resume workout in progress
        </button>
      )}

      {/* Routines */}
      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-muted">Routines</h2>
          <button
            onClick={() => setRoutineSheet({ open: true })}
            className="flex items-center gap-1 text-sm font-medium text-accent"
          >
            <Plus size={16} /> New
          </button>
        </div>
        {routines.map((r) => (
          <div key={r.id} className={card}>
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="font-semibold">{r.name}</div>
                <div className="truncate text-xs text-faint">
                  {r.exercises.length} exercises ·{" "}
                  {r.exercises
                    .slice(0, 3)
                    .map((e) => exName.get(e.exerciseId))
                    .filter(Boolean)
                    .join(", ")}
                  {r.exercises.length > 3 ? "…" : ""}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <button
                  aria-label="Edit routine"
                  onClick={() => setRoutineSheet({ open: true, routine: r })}
                  className="rounded-full bg-surface2 p-2 text-muted"
                >
                  <Pencil size={15} />
                </button>
                <button
                  aria-label="Delete routine"
                  onClick={() => archiveRoutine(r)}
                  className="rounded-full bg-surface2 p-2 text-muted"
                >
                  <X size={15} />
                </button>
                <button
                  onClick={() => startWorkout(r)}
                  disabled={!!db.activeWorkoutId}
                  className="ml-1 flex h-9 items-center gap-1 rounded-xl px-3 text-sm font-semibold text-white active:opacity-80 disabled:opacity-40"
                  style={{ background: "var(--color-train)" }}
                >
                  <Play size={14} /> Start
                </button>
              </div>
            </div>
          </div>
        ))}
        <button
          onClick={() => startWorkout()}
          disabled={!!db.activeWorkoutId}
          className="w-full rounded-[16px] border border-dashed border-line py-3 text-sm text-muted disabled:opacity-40"
        >
          Start empty workout
        </button>
      </section>

      {/* History */}
      {history.length > 0 && (
        <section className="space-y-2">
          <h2 className="font-semibold text-muted">Recent workouts</h2>
          <div className={`${card} divide-y divide-line !p-0`}>
            {history.map((w) => (
              <div key={w.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <div className="text-sm font-medium">{w.name}</div>
                  <div className="text-xs text-faint">{fmtShort(todayStrOf(w.startedAt))}</div>
                </div>
                <div className="tnum text-right text-xs text-muted">
                  {w.sets.length} sets
                  <br />
                  {fmtWeight(workoutVolumeKg(w.sets), db.settings.unitWeight)} volume
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Exercise library */}
      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-muted">Exercise library</h2>
          <button
            onClick={() => setExerciseSheet({ open: true })}
            className="flex items-center gap-1 text-sm font-medium text-accent"
          >
            <Plus size={16} /> Add
          </button>
        </div>
        <div className="flex gap-2 overflow-x-auto pb-1">
          {(["all", ...MUSCLE_GROUPS] as const).map((g) => (
            <button
              key={g}
              onClick={() => setGroupFilter(g)}
              className={`shrink-0 rounded-full px-3 py-1.5 text-xs font-medium capitalize ${
                groupFilter === g ? "bg-ink text-bg" : "bg-surface2 text-muted"
              }`}
            >
              {g}
            </button>
          ))}
        </div>
        <div className={`${card} divide-y divide-line !p-0`}>
          {exercises
            .filter((e) => groupFilter === "all" || e.muscleGroup === groupFilter)
            .map((e) => (
              <div key={e.id} className="flex items-center justify-between px-4 py-2.5">
                <div>
                  <div className="text-sm">{e.name}</div>
                  <div className="text-xs capitalize text-faint">{e.muscleGroup}</div>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    aria-label="Edit exercise"
                    onClick={() => setExerciseSheet({ open: true, exercise: e })}
                    className="p-1.5 text-faint"
                  >
                    <Pencil size={15} />
                  </button>
                  <button
                    aria-label="Delete exercise"
                    onClick={() => archiveExercise(e)}
                    className="p-1.5 text-faint"
                  >
                    <X size={15} />
                  </button>
                </div>
              </div>
            ))}
        </div>
      </section>

      <RoutineSheet
        key={routineSheet.routine?.id ?? "new"}
        state={routineSheet}
        onClose={() => setRoutineSheet({ open: false })}
      />
      <ExerciseSheet
        key={exerciseSheet.exercise?.id ?? "new-ex"}
        state={exerciseSheet}
        onClose={() => setExerciseSheet({ open: false })}
      />
    </div>
  );
}

function todayStrOf(ts: number): string {
  return todayStr(new Date(ts));
}

function RoutineSheet({
  state,
  onClose,
}: {
  state: { open: boolean; routine?: Routine };
  onClose: () => void;
}) {
  const { db, update } = useStore();
  const [name, setName] = useState(state.routine?.name ?? "");
  const [items, setItems] = useState(state.routine?.exercises ?? []);
  const [pick, setPick] = useState("");

  const available = db.exercises.filter((e) => !e.archived);
  const exName = new Map(db.exercises.map((e) => [e.id, e.name]));

  const save = () => {
    const n = name.trim();
    if (!n || items.length === 0) return;
    update((d) => ({
      ...d,
      routines: state.routine
        ? d.routines.map((r) =>
            r.id === state.routine!.id ? { ...r, name: n, exercises: items } : r
          )
        : [...d.routines, { id: uid(), name: n, exercises: items }],
    }));
    onClose();
  };

  return (
    <Sheet open={state.open} onClose={onClose} title={state.routine ? "Edit routine" : "New routine"}>
      <input
        placeholder='Name (e.g. "Workout A — Push")'
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="mb-3 h-11 w-full rounded-xl bg-surface2 px-3"
      />
      <ul className="mb-3 space-y-2">
        {items.map((it, i) => (
          <li key={i} className="flex items-center gap-2 rounded-xl bg-surface2 px-3 py-2">
            <span className="flex-1 text-sm">{exName.get(it.exerciseId)}</span>
            <button
              aria-label="Fewer sets"
              onClick={() =>
                setItems((xs) =>
                  xs.map((x, j) =>
                    j === i ? { ...x, targetSets: Math.max(1, x.targetSets - 1) } : x
                  )
                )
              }
              className="rounded-lg bg-surface p-1.5 text-muted"
            >
              <Minus size={14} />
            </button>
            <span className="tnum w-12 text-center text-sm">{it.targetSets} sets</span>
            <button
              aria-label="More sets"
              onClick={() =>
                setItems((xs) =>
                  xs.map((x, j) => (j === i ? { ...x, targetSets: x.targetSets + 1 } : x))
                )
              }
              className="rounded-lg bg-surface p-1.5 text-muted"
            >
              <Plus size={14} />
            </button>
            <button
              aria-label="Remove exercise"
              onClick={() => setItems((xs) => xs.filter((_, j) => j !== i))}
              className="p-1 text-faint"
            >
              <X size={15} />
            </button>
          </li>
        ))}
      </ul>
      <div className="mb-4 flex gap-2">
        <select
          aria-label="Pick exercise"
          value={pick}
          onChange={(e) => setPick(e.target.value)}
          className="h-11 flex-1 rounded-xl bg-surface2 px-3 text-sm"
        >
          <option value="">Add exercise…</option>
          {MUSCLE_GROUPS.map((g) => {
            const group = available.filter((e) => e.muscleGroup === g);
            return group.length ? (
              <optgroup key={g} label={g}>
                {group.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.name}
                  </option>
                ))}
              </optgroup>
            ) : null;
          })}
        </select>
        <button
          onClick={() => {
            if (!pick) return;
            setItems((xs) => [...xs, { exerciseId: pick, targetSets: 3 }]);
            setPick("");
          }}
          className="h-11 rounded-xl bg-surface2 px-4 text-sm font-medium text-accent"
        >
          Add
        </button>
      </div>
      <button
        onClick={save}
        className="h-12 w-full rounded-2xl bg-accent font-semibold text-white active:opacity-80"
      >
        Save routine
      </button>
    </Sheet>
  );
}

function ExerciseSheet({
  state,
  onClose,
}: {
  state: { open: boolean; exercise?: Exercise };
  onClose: () => void;
}) {
  const { update } = useStore();
  const [name, setName] = useState(state.exercise?.name ?? "");
  const [group, setGroup] = useState<MuscleGroup>(state.exercise?.muscleGroup ?? "chest");

  const save = () => {
    const n = name.trim();
    if (!n) return;
    update((d) => ({
      ...d,
      exercises: state.exercise
        ? d.exercises.map((e) =>
            e.id === state.exercise!.id ? { ...e, name: n, muscleGroup: group } : e
          )
        : [...d.exercises, { id: uid(), name: n, muscleGroup: group }],
    }));
    onClose();
  };

  return (
    <Sheet open={state.open} onClose={onClose} title={state.exercise ? "Edit exercise" : "New exercise"}>
      <input
        placeholder="Exercise name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="mb-3 h-11 w-full rounded-xl bg-surface2 px-3"
      />
      <select
        aria-label="Muscle group"
        value={group}
        onChange={(e) => setGroup(e.target.value as MuscleGroup)}
        className="mb-4 h-11 w-full rounded-xl bg-surface2 px-3 text-sm capitalize"
      >
        {MUSCLE_GROUPS.map((g) => (
          <option key={g} value={g}>
            {g}
          </option>
        ))}
      </select>
      <button
        onClick={save}
        className="h-12 w-full rounded-2xl bg-accent font-semibold text-white active:opacity-80"
      >
        Save
      </button>
    </Sheet>
  );
}
