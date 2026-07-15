# FitLog

A personal health, fitness & nutrition tracker — mobile-first PWA, dark-mode by
default for the gym. Built per the plan in
[`docs/health-fitness-tracker/DEVELOPMENT_PLAN.md`](../../docs/health-fitness-tracker/DEVELOPMENT_PLAN.md).

## Run it

```bash
# from the repo root
pnpm install
pnpm dev:fitlog     # then open http://localhost:3001
```

Open it on your phone (or in responsive dev tools) — the layout is designed for
a phone-width screen and installs to the home screen as a standalone app.

## What's in the MVP

- **Nutrition** — meal-grouped daily log, one-tap frequent-food chips, quick
  manual macro entry (kcal derived from macros if left blank), favorites,
  calorie ring + protein/carbs/fat bars, water cups.
- **Weight** — one weigh-in per day (upsert), trend chart with 7-day rolling
  average, 7D/30D/3M/1Y ranges, weekly-average table.
- **Measurements** — 7 circumference metrics, previous values as placeholders,
  comparison table with change column.
- **Workouts** — seeded editable exercise library, routine templates
  (Push/Pull/Legs seeded), active logger with set/weight/rep steppers,
  pre-filled inputs, and "last time" progressive-overload hints.
- **Settings** — daily goals, kg/lb display units, JSON export, full reset.

## Data storage

Currently **local-first**: the entire database lives in `localStorage`
(`fitlog:v1`), every log action is synchronous/optimistic, and JSON export is
the backup path. The domain model in `lib/types.ts` mirrors the Postgres schema
in `supabase/migrations/0001_init.sql` (RLS-protected, multi-user-ready), so
the cloud phase is an adapter swap in `lib/store.tsx` — not a rewrite.

## Structure

```
app/            Next.js App Router pages (Today, Food, Train, Trends, Settings)
components/     shell (TabBar, Sheet) + widgets (Ring, MacroBar, WeightChart, …)
lib/            types, seed data, localStorage store, derived calculations
supabase/       cloud-mode schema, ready for `supabase db push`
```
