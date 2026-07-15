"use client";

import { useMemo, useState } from "react";
import { Search, Star, X } from "lucide-react";
import { Sheet } from "./Sheet";
import { useStore, useToast } from "@/lib/store";
import { frequentFoods } from "@/lib/calc";
import { round1 } from "@/lib/format";
import { uid, type Food, type Meal } from "@/lib/types";

const MEAL_LABEL: Record<Meal, string> = {
  breakfast: "Breakfast",
  lunch: "Lunch",
  dinner: "Dinner",
  snack: "Snacks",
};

export function AddFoodSheet({
  open,
  onClose,
  meal,
  date,
}: {
  open: boolean;
  onClose: () => void;
  meal: Meal;
  date: string;
}) {
  const { db, update } = useStore();
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [servings, setServings] = useState("1");
  const [quick, setQuick] = useState({ desc: "", kcal: "", protein: "", carbs: "", fat: "" });
  const [saveToFoods, setSaveToFoods] = useState(false);

  const chips = frequentFoods(db, 8);
  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return db.foods.filter((f) => !f.archived && f.name.toLowerCase().includes(q)).slice(0, 12);
  }, [db.foods, query]);

  const logFood = (food: Food, n = 1) => {
    const entry = {
      id: uid(),
      date,
      loggedAt: Date.now(),
      meal,
      foodId: food.id,
      description: food.name,
      servings: n,
      kcal: round1(food.kcal * n),
      protein: round1(food.protein * n),
      carbs: round1(food.carbs * n),
      fat: round1(food.fat * n),
    };
    update((d) => ({
      ...d,
      foodEntries: [...d.foodEntries, entry],
      foods: d.foods.map((f) => (f.id === food.id ? { ...f, useCount: f.useCount + 1 } : f)),
    }));
    toast.show(`Logged ${food.name}`, () =>
      update((d) => ({ ...d, foodEntries: d.foodEntries.filter((e) => e.id !== entry.id) }))
    );
    onClose();
  };

  const logQuick = () => {
    const p = parseFloat(quick.protein) || 0;
    const c = parseFloat(quick.carbs) || 0;
    const f = parseFloat(quick.fat) || 0;
    // kcal derived from macros (4/4/9) when left empty
    const kcal = quick.kcal !== "" ? parseFloat(quick.kcal) || 0 : p * 4 + c * 4 + f * 9;
    if (kcal <= 0 && p + c + f <= 0) return;
    const desc = quick.desc.trim() || "Quick entry";
    let foodId: string | undefined;
    if (saveToFoods && quick.desc.trim()) {
      foodId = uid();
    }
    const entry = {
      id: uid(),
      date,
      loggedAt: Date.now(),
      meal,
      foodId,
      description: desc,
      servings: 1,
      kcal: round1(kcal),
      protein: round1(p),
      carbs: round1(c),
      fat: round1(f),
    };
    update((d) => ({
      ...d,
      foodEntries: [...d.foodEntries, entry],
      foods: foodId
        ? [
            ...d.foods,
            { id: foodId, name: desc, kcal: round1(kcal), protein: p, carbs: c, fat: f, favorite: false, useCount: 1 },
          ]
        : d.foods,
    }));
    toast.show(`Logged ${desc}`, () =>
      update((d) => ({
        ...d,
        foodEntries: d.foodEntries.filter((e) => e.id !== entry.id),
        foods: foodId ? d.foods.filter((f2) => f2.id !== foodId) : d.foods,
      }))
    );
    setQuick({ desc: "", kcal: "", protein: "", carbs: "", fat: "" });
    setSaveToFoods(false);
    onClose();
  };

  const toggleFavorite = (food: Food) =>
    update((d) => ({
      ...d,
      foods: d.foods.map((f) => (f.id === food.id ? { ...f, favorite: !f.favorite } : f)),
    }));

  const archiveFood = (food: Food) => {
    update((d) => ({
      ...d,
      foods: d.foods.map((f) => (f.id === food.id ? { ...f, archived: true } : f)),
    }));
    toast.show(`Removed ${food.name}`, () =>
      update((d) => ({
        ...d,
        foods: d.foods.map((f) => (f.id === food.id ? { ...f, archived: false } : f)),
      }))
    );
  };

  const num = "tnum h-11 w-full rounded-xl bg-surface2 px-3 text-center";

  return (
    <Sheet open={open} onClose={onClose} title={`Add to ${MEAL_LABEL[meal]}`}>
      {chips.length > 0 && (
        <>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">
            Frequent · one tap logs 1 serving
          </p>
          <div className="mb-4 flex flex-wrap gap-2">
            {chips.map((f) => (
              <button
                key={f.id}
                onClick={() => logFood(f)}
                className="rounded-full border border-line bg-surface2 px-3 py-2 text-sm active:bg-line"
              >
                {f.name} <span className="tnum text-faint">{Math.round(f.kcal)}</span>
              </button>
            ))}
          </div>
        </>
      )}

      <div className="mb-2 flex items-center gap-2 rounded-xl bg-surface2 px-3">
        <Search size={16} className="text-faint" />
        <input
          placeholder="Search my foods…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="h-11 w-full bg-transparent"
        />
      </div>
      {results.length > 0 && (
        <div className="mb-4 divide-y divide-line rounded-xl border border-line">
          {results.map((f) => (
            <div key={f.id} className="flex items-center gap-2 px-3 py-2">
              <button onClick={() => logFood(f, parseFloat(servings) || 1)} className="flex-1 text-left">
                <div className="text-sm font-medium">{f.name}</div>
                <div className="tnum text-xs text-faint">
                  {Math.round(f.kcal)} kcal · P {f.protein} · C {f.carbs} · F {f.fat}
                  {f.servingLabel ? ` · ${f.servingLabel}` : ""}
                </div>
              </button>
              <input
                aria-label="Servings"
                inputMode="decimal"
                value={servings}
                onChange={(e) => setServings(e.target.value)}
                className="tnum h-9 w-12 rounded-lg bg-surface2 text-center text-sm"
              />
              <button aria-label="Toggle favorite" onClick={() => toggleFavorite(f)}>
                <Star size={16} className={f.favorite ? "fill-carbs text-carbs" : "text-faint"} />
              </button>
              <button aria-label="Remove food" onClick={() => archiveFood(f)}>
                <X size={16} className="text-faint" />
              </button>
            </div>
          ))}
        </div>
      )}

      <p className="mb-2 mt-2 text-xs font-semibold uppercase tracking-wide text-faint">
        Or quick entry
      </p>
      <input
        placeholder="Description (e.g. chicken salad)"
        value={quick.desc}
        onChange={(e) => setQuick((q) => ({ ...q, desc: e.target.value }))}
        className="mb-2 h-11 w-full rounded-xl bg-surface2 px-3"
      />
      <div className="mb-2 grid grid-cols-4 gap-2">
        {(
          [
            ["kcal", "kcal"],
            ["protein", "P (g)"],
            ["carbs", "C (g)"],
            ["fat", "F (g)"],
          ] as const
        ).map(([key, label]) => (
          <label key={key} className="block">
            <span className="mb-1 block text-center text-[11px] text-faint">{label}</span>
            <input
              inputMode="decimal"
              value={quick[key]}
              onChange={(e) => setQuick((q) => ({ ...q, [key]: e.target.value }))}
              className={num}
            />
          </label>
        ))}
      </div>
      <label className="mb-3 flex items-center gap-2 text-sm text-muted">
        <input
          type="checkbox"
          checked={saveToFoods}
          onChange={(e) => setSaveToFoods(e.target.checked)}
          className="h-4 w-4 accent-[var(--color-accent)]"
        />
        Also save to my foods
      </label>
      <button
        onClick={logQuick}
        className="h-12 w-full rounded-2xl bg-accent font-semibold text-white active:opacity-80"
      >
        Log it
      </button>
      <p className="mt-2 text-xs text-faint">
        Leave kcal empty to derive it from macros (4/4/9).
      </p>
    </Sheet>
  );
}
