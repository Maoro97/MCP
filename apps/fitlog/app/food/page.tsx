"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ChevronLeft, ChevronRight, Plus, X } from "lucide-react";
import { useStore, useToast } from "@/lib/store";
import { dayTotals, mealEntries } from "@/lib/calc";
import { addDays, fmtDay, todayStr } from "@/lib/format";
import { MEALS, type Meal } from "@/lib/types";
import { AddFoodSheet } from "@/components/AddFoodSheet";

const MEAL_LABEL: Record<Meal, string> = {
  breakfast: "Breakfast",
  lunch: "Lunch",
  dinner: "Dinner",
  snack: "Snacks",
};

function mealForNow(): Meal {
  const h = new Date().getHours();
  if (h < 11) return "breakfast";
  if (h < 15) return "lunch";
  if (h < 18) return "snack";
  return "dinner";
}

function FoodPageInner() {
  const { db, update } = useStore();
  const toast = useToast();
  const params = useSearchParams();
  const [date, setDate] = useState(todayStr());
  const [sheet, setSheet] = useState<{ open: boolean; meal: Meal }>({
    open: false,
    meal: mealForNow(),
  });

  // Global quick-add routes here with ?add=1
  useEffect(() => {
    if (params.get("add") === "1") {
      setSheet({ open: true, meal: mealForNow() });
    }
  }, [params]);

  const totals = dayTotals(db, date);
  const isToday = date === todayStr();

  const removeEntry = (id: string) => {
    const entry = db.foodEntries.find((e) => e.id === id);
    if (!entry) return;
    update((d) => ({ ...d, foodEntries: d.foodEntries.filter((e) => e.id !== id) }));
    toast.show(`Removed ${entry.description}`, () =>
      update((d) => ({ ...d, foodEntries: [...d.foodEntries, entry] }))
    );
  };

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <button
          aria-label="Previous day"
          onClick={() => setDate((d) => addDays(d, -1))}
          className="rounded-full bg-surface p-2 text-muted"
        >
          <ChevronLeft size={20} />
        </button>
        <div className="text-center">
          <h1 className="text-lg font-bold">{isToday ? "Today" : fmtDay(date)}</h1>
          <p className="tnum text-xs text-faint">
            {Math.round(totals.kcal)} kcal · P {Math.round(totals.protein)} · C{" "}
            {Math.round(totals.carbs)} · F {Math.round(totals.fat)}
          </p>
        </div>
        <button
          aria-label="Next day"
          onClick={() => setDate((d) => addDays(d, 1))}
          disabled={isToday}
          className="rounded-full bg-surface p-2 text-muted disabled:opacity-30"
        >
          <ChevronRight size={20} />
        </button>
      </header>

      {MEALS.map((meal) => {
        const entries = mealEntries(db, date, meal);
        const kcal = entries.reduce((s, e) => s + e.kcal, 0);
        return (
          <section key={meal} className="rounded-[16px] border border-line bg-surface p-4">
            <div className="mb-1 flex items-center justify-between">
              <h2 className="font-semibold">{MEAL_LABEL[meal]}</h2>
              <span className="tnum text-sm text-muted">{Math.round(kcal)} kcal</span>
            </div>
            {entries.length === 0 && <p className="py-1 text-sm text-faint">Nothing logged</p>}
            <ul className="divide-y divide-line">
              {entries.map((e) => (
                <li key={e.id} className="flex items-center gap-2 py-2">
                  <div className="flex-1">
                    <div className="text-sm">
                      {e.description}
                      {e.servings !== 1 && (
                        <span className="tnum text-faint"> ×{e.servings}</span>
                      )}
                    </div>
                    <div className="tnum text-xs text-faint">
                      P {Math.round(e.protein)} · C {Math.round(e.carbs)} · F {Math.round(e.fat)}
                    </div>
                  </div>
                  <span className="tnum text-sm">{Math.round(e.kcal)}</span>
                  <button
                    aria-label="Remove entry"
                    onClick={() => removeEntry(e.id)}
                    className="p-1 text-faint"
                  >
                    <X size={16} />
                  </button>
                </li>
              ))}
            </ul>
            <button
              onClick={() => setSheet({ open: true, meal })}
              className="mt-1 flex items-center gap-1 text-sm font-medium text-accent"
            >
              <Plus size={16} /> Add
            </button>
          </section>
        );
      })}

      <AddFoodSheet
        open={sheet.open}
        onClose={() => setSheet((s) => ({ ...s, open: false }))}
        meal={sheet.meal}
        date={date}
      />
    </div>
  );
}

export default function FoodPage() {
  return (
    <Suspense fallback={null}>
      <FoodPageInner />
    </Suspense>
  );
}
