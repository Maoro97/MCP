// First-run seed: a starter exercise library, three example routines, and a
// handful of favorite foods so the one-tap chips work immediately.
// Everything is editable/deletable in the app.

import type { DB, Exercise, Food, MuscleGroup, Routine } from "./types";
import { uid } from "./types";

const EXERCISES: [string, MuscleGroup][] = [
  ["Bench Press", "chest"],
  ["Incline Dumbbell Press", "chest"],
  ["Chest Fly (Machine)", "chest"],
  ["Cable Crossover", "chest"],
  ["Push-Up", "chest"],
  ["Deadlift", "back"],
  ["Pull-Up", "back"],
  ["Lat Pulldown", "back"],
  ["Barbell Row", "back"],
  ["Seated Cable Row", "back"],
  ["Face Pull", "back"],
  ["Overhead Press", "shoulders"],
  ["Dumbbell Shoulder Press", "shoulders"],
  ["Lateral Raise", "shoulders"],
  ["Rear Delt Fly", "shoulders"],
  ["Barbell Curl", "biceps"],
  ["Dumbbell Curl", "biceps"],
  ["Hammer Curl", "biceps"],
  ["Preacher Curl", "biceps"],
  ["Triceps Pushdown", "triceps"],
  ["Skull Crusher", "triceps"],
  ["Overhead Triceps Extension", "triceps"],
  ["Dips", "triceps"],
  ["Squat", "legs"],
  ["Leg Press", "legs"],
  ["Romanian Deadlift", "legs"],
  ["Leg Extension", "legs"],
  ["Leg Curl", "legs"],
  ["Calf Raise", "legs"],
  ["Walking Lunge", "legs"],
  ["Bulgarian Split Squat", "legs"],
  ["Hip Thrust", "glutes"],
  ["Cable Kickback", "glutes"],
  ["Plank", "core"],
  ["Crunch", "core"],
  ["Hanging Leg Raise", "core"],
  ["Cable Woodchopper", "core"],
  ["Russian Twist", "core"],
];

const FOODS: [string, number, number, number, number, string][] = [
  // name, kcal, protein, carbs, fat, serving
  ["Oatmeal + whey", 320, 30, 40, 6, "1 bowl"],
  ["3 eggs", 210, 18, 1, 15, "3 eggs"],
  ["Greek yogurt", 150, 17, 8, 5, "200 g"],
  ["Chicken & rice", 620, 45, 70, 12, "1 plate"],
  ["Banana", 100, 1, 25, 0, "1 medium"],
  ["Protein shake", 120, 24, 3, 1, "1 scoop"],
  ["Tuna sandwich", 350, 25, 40, 8, "1 sandwich"],
  ["Cottage cheese", 180, 28, 7, 4, "250 g"],
];

export function seedDB(): DB {
  const exercises: Exercise[] = EXERCISES.map(([name, muscleGroup]) => ({
    id: uid(),
    name,
    muscleGroup,
  }));

  const byName = new Map(exercises.map((e) => [e.name, e.id]));
  const routine = (name: string, names: string[]): Routine => ({
    id: uid(),
    name,
    exercises: names
      .map((n) => byName.get(n))
      .filter((id): id is string => !!id)
      .map((exerciseId) => ({ exerciseId, targetSets: 3 })),
  });

  const routines: Routine[] = [
    routine("Workout A — Push", [
      "Bench Press",
      "Incline Dumbbell Press",
      "Overhead Press",
      "Lateral Raise",
      "Triceps Pushdown",
    ]),
    routine("Workout B — Pull", [
      "Deadlift",
      "Lat Pulldown",
      "Barbell Row",
      "Face Pull",
      "Barbell Curl",
    ]),
    routine("Workout C — Legs", [
      "Squat",
      "Leg Press",
      "Romanian Deadlift",
      "Leg Curl",
      "Calf Raise",
    ]),
  ];

  const foods: Food[] = FOODS.map(([name, kcal, protein, carbs, fat, servingLabel]) => ({
    id: uid(),
    name,
    kcal,
    protein,
    carbs,
    fat,
    servingLabel,
    favorite: true,
    useCount: 0,
  }));

  return {
    version: 1,
    foods,
    foodEntries: [],
    water: [],
    weights: [],
    measurements: [],
    exercises,
    routines,
    workouts: [],
    goals: { kcal: 2200, protein: 160, carbs: 220, fat: 70, waterMl: 2000 },
    settings: { unitWeight: "kg" },
  };
}
