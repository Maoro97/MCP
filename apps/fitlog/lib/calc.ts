// Derived data. In cloud mode these become SQL views/functions
// (daily_nutrition, weight_rolling_avg, last_performance) — see the migration.

import type { DB, Food, Macros, Meal, Routine, WorkoutSet, WeightEntry } from "./types";
import { addDays } from "./format";

export function dayTotals(db: DB, date: string): Macros {
  const t: Macros = { kcal: 0, protein: 0, carbs: 0, fat: 0 };
  for (const e of db.foodEntries) {
    if (e.date !== date) continue;
    t.kcal += e.kcal;
    t.protein += e.protein;
    t.carbs += e.carbs;
    t.fat += e.fat;
  }
  return t;
}

export function dayWaterMl(db: DB, date: string): number {
  return db.water.filter((w) => w.date === date).reduce((s, w) => s + w.amountMl, 0);
}

export function mealEntries(db: DB, date: string, meal: Meal) {
  return db.foodEntries
    .filter((e) => e.date === date && e.meal === meal)
    .sort((a, b) => a.loggedAt - b.loggedAt);
}

/** Weigh-ins sorted by date ascending. */
export function weightSeries(db: DB): WeightEntry[] {
  return [...db.weights].sort((a, b) => (a.date < b.date ? -1 : 1));
}

/** Trailing N-day average ending at each entry's date (matches the SQL view). */
export function rollingAvg(series: WeightEntry[], days = 7): { date: string; avg: number }[] {
  return series.map((e) => {
    const from = addDays(e.date, -(days - 1));
    const win = series.filter((w) => w.date >= from && w.date <= e.date);
    return { date: e.date, avg: win.reduce((s, w) => s + w.weightKg, 0) / win.length };
  });
}

export function latestWeight(db: DB): WeightEntry | undefined {
  const s = weightSeries(db);
  return s[s.length - 1];
}

/** Change between this week's average and the previous week's, if both exist. */
export function weeklyDeltaKg(db: DB, today: string): number | undefined {
  const s = weightSeries(db);
  const avg = (from: string, to: string) => {
    const win = s.filter((w) => w.date >= from && w.date <= to);
    return win.length ? win.reduce((x, w) => x + w.weightKg, 0) / win.length : undefined;
  };
  const cur = avg(addDays(today, -6), today);
  const prev = avg(addDays(today, -13), addDays(today, -7));
  return cur !== undefined && prev !== undefined ? cur - prev : undefined;
}

/**
 * Progressive-overload helper: the sets of the most recent *finished* workout
 * that included this exercise (excluding the workout in progress).
 */
export function lastPerformance(
  db: DB,
  exerciseId: string,
  excludeWorkoutId?: string
): WorkoutSet[] | undefined {
  const done = db.workouts
    .filter((w) => w.finishedAt && w.id !== excludeWorkoutId)
    .sort((a, b) => b.startedAt - a.startedAt);
  for (const w of done) {
    const sets = w.sets
      .filter((s) => s.exerciseId === exerciseId)
      .sort((a, b) => a.setNumber - b.setNumber);
    if (sets.length) return sets;
  }
  return undefined;
}

/** Favorites first, then most-used — powers the one-tap chips. */
export function frequentFoods(db: DB, limit = 8): Food[] {
  return db.foods
    .filter((f) => !f.archived)
    .sort((a, b) =>
      a.favorite !== b.favorite ? (a.favorite ? -1 : 1) : b.useCount - a.useCount
    )
    .slice(0, limit);
}

/** Suggest the least-recently-performed routine for the dashboard. */
export function nextRoutine(db: DB): Routine | undefined {
  const routines = db.routines.filter((r) => !r.archived);
  if (!routines.length) return undefined;
  const lastDone = new Map<string, number>();
  for (const w of db.workouts) {
    if (w.routineId && w.finishedAt) {
      lastDone.set(w.routineId, Math.max(lastDone.get(w.routineId) ?? 0, w.startedAt));
    }
  }
  return [...routines].sort(
    (a, b) => (lastDone.get(a.id) ?? 0) - (lastDone.get(b.id) ?? 0)
  )[0];
}

export function workoutVolumeKg(sets: WorkoutSet[]): number {
  return sets.reduce((s, x) => s + x.weightKg * x.reps, 0);
}
