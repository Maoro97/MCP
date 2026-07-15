// Domain model. Mirrors supabase/migrations/0001_init.sql — the local store
// is a stand-in for the cloud database, so shapes must stay in sync.

export type Meal = "breakfast" | "lunch" | "dinner" | "snack";
export const MEALS: Meal[] = ["breakfast", "lunch", "dinner", "snack"];

export interface Macros {
  kcal: number;
  protein: number;
  carbs: number;
  fat: number;
}

export interface Food extends Macros {
  id: string;
  name: string;
  servingLabel?: string;
  favorite: boolean;
  useCount: number;
  archived?: boolean;
}

// Macros on an entry are a snapshot (servings already applied) so editing a
// saved food later never rewrites history.
export interface FoodEntry extends Macros {
  id: string;
  date: string; // user-local YYYY-MM-DD
  loggedAt: number;
  meal: Meal;
  foodId?: string;
  description: string;
  servings: number;
}

export interface WaterEntry {
  id: string;
  date: string;
  loggedAt: number;
  amountMl: number;
}

export interface WeightEntry {
  id: string;
  date: string; // unique per day — logging twice replaces
  loggedAt: number;
  weightKg: number;
}

export type MetricKey =
  | "chest"
  | "armL"
  | "armR"
  | "waist"
  | "abdomen"
  | "thighL"
  | "thighR";

export const METRICS: { key: MetricKey; label: string }[] = [
  { key: "chest", label: "Chest" },
  { key: "armL", label: "Left arm" },
  { key: "armR", label: "Right arm" },
  { key: "waist", label: "Waist" },
  { key: "abdomen", label: "Abdomen" },
  { key: "thighL", label: "Left thigh" },
  { key: "thighR", label: "Right thigh" },
];

export interface MeasurementSession {
  id: string;
  date: string;
  loggedAt: number;
  values: Partial<Record<MetricKey, number>>; // centimeters
}

export type MuscleGroup =
  | "chest"
  | "back"
  | "shoulders"
  | "biceps"
  | "triceps"
  | "legs"
  | "glutes"
  | "core"
  | "other";

export const MUSCLE_GROUPS: MuscleGroup[] = [
  "chest",
  "back",
  "shoulders",
  "biceps",
  "triceps",
  "legs",
  "glutes",
  "core",
  "other",
];

export interface Exercise {
  id: string;
  name: string;
  muscleGroup: MuscleGroup;
  archived?: boolean;
}

export interface RoutineExercise {
  exerciseId: string;
  targetSets: number;
}

export interface Routine {
  id: string;
  name: string;
  exercises: RoutineExercise[];
  archived?: boolean;
}

export interface WorkoutSet {
  id: string;
  exerciseId: string;
  setNumber: number;
  weightKg: number; // 0 = bodyweight
  reps: number;
  loggedAt: number;
}

export interface Workout {
  id: string;
  routineId?: string;
  name: string;
  startedAt: number;
  finishedAt?: number;
  exerciseOrder: string[];
  sets: WorkoutSet[];
}

export interface Goals {
  kcal: number;
  protein: number;
  carbs: number;
  fat: number;
  waterMl: number;
  targetWeightKg?: number;
}

export interface Settings {
  unitWeight: "kg" | "lb";
}

export interface DB {
  version: 1;
  foods: Food[];
  foodEntries: FoodEntry[];
  water: WaterEntry[];
  weights: WeightEntry[];
  measurements: MeasurementSession[];
  exercises: Exercise[];
  routines: Routine[];
  workouts: Workout[];
  goals: Goals;
  settings: Settings;
  activeWorkoutId?: string;
}

export const uid = (): string =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2) + Date.now().toString(36);
