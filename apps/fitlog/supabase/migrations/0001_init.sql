-- FitLog schema — Phase 0 (cloud mode).
-- Multi-tenant from row one: every table carries user_id and an RLS policy.
-- The local store in lib/store.tsx mirrors these shapes.

-- ---------------------------------------------------------------- profiles
create table profiles (
  id           uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  timezone     text not null default 'Asia/Jerusalem',
  unit_weight  text not null default 'kg' check (unit_weight in ('kg','lb')),
  unit_length  text not null default 'cm' check (unit_length in ('cm','in')),
  created_at   timestamptz not null default now()
);

-- goals are versioned: history stays honest when targets change
create table goals (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references auth.users(id) on delete cascade,
  effective_from   date not null default current_date,
  calories_kcal    int,
  protein_g        int,
  carbs_g          int,
  fat_g            int,
  water_ml         int,
  target_weight_kg numeric(5,2),
  created_at       timestamptz not null default now()
);

-- ---------------------------------------------------------------- nutrition
create table foods (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  name          text not null,
  calories_kcal numeric(7,1) not null,
  protein_g     numeric(6,1) not null default 0,
  carbs_g       numeric(6,1) not null default 0,
  fat_g         numeric(6,1) not null default 0,
  serving_label text,
  is_favorite   boolean not null default false,
  use_count     int not null default 0,
  archived_at   timestamptz,
  created_at    timestamptz not null default now()
);

create table food_log_entries (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  logged_at     timestamptz not null default now(),
  log_date      date not null,
  meal          text not null check (meal in ('breakfast','lunch','dinner','snack')),
  food_id       uuid references foods(id),
  description   text,
  servings      numeric(5,2) not null default 1,
  -- snapshot: totals for THIS entry, servings applied — editing a food never rewrites history
  calories_kcal numeric(7,1) not null,
  protein_g     numeric(6,1) not null default 0,
  carbs_g       numeric(6,1) not null default 0,
  fat_g         numeric(6,1) not null default 0
);
create index food_log_entries_day on food_log_entries (user_id, log_date);

create table water_log_entries (
  id        uuid primary key default gen_random_uuid(),
  user_id   uuid not null references auth.users(id) on delete cascade,
  logged_at timestamptz not null default now(),
  log_date  date not null,
  amount_ml int not null check (amount_ml > 0)
);
create index water_log_entries_day on water_log_entries (user_id, log_date);

create view daily_nutrition as
select user_id, log_date,
       sum(calories_kcal) as calories_kcal,
       sum(protein_g)     as protein_g,
       sum(carbs_g)       as carbs_g,
       sum(fat_g)         as fat_g
from food_log_entries
group by user_id, log_date;

-- ---------------------------------------------------------------- weight
create table weight_entries (
  id        uuid primary key default gen_random_uuid(),
  user_id   uuid not null references auth.users(id) on delete cascade,
  logged_at timestamptz not null default now(),
  log_date  date not null,
  weight_kg numeric(5,2) not null check (weight_kg between 20 and 400),
  note      text
);
create unique index weight_one_per_day on weight_entries (user_id, log_date);

create view weight_rolling_avg as
select user_id, log_date, weight_kg,
       avg(weight_kg) over (
         partition by user_id order by log_date
         range between interval '6 days' preceding and current row
       ) as avg_7d
from weight_entries;

-- ------------------------------------------------------------ measurements
create table measurement_sessions (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references auth.users(id) on delete cascade,
  measured_at    timestamptz not null default now(),
  log_date       date not null,
  chest_cm       numeric(5,1),
  arm_left_cm    numeric(5,1),
  arm_right_cm   numeric(5,1),
  waist_cm       numeric(5,1),
  abdomen_cm     numeric(5,1),
  thigh_left_cm  numeric(5,1),
  thigh_right_cm numeric(5,1),
  note           text
);
create index measurement_sessions_day on measurement_sessions (user_id, log_date);

-- ---------------------------------------------------------------- workouts
create table exercises (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  name         text not null,
  muscle_group text not null check (muscle_group in
    ('chest','back','shoulders','biceps','triceps','legs','glutes','core','other')),
  archived_at  timestamptz,
  created_at   timestamptz not null default now()
);

create table routines (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  name        text not null,
  position    int not null default 0,
  archived_at timestamptz,
  created_at  timestamptz not null default now()
);

create table routine_exercises (
  id          uuid primary key default gen_random_uuid(),
  routine_id  uuid not null references routines(id) on delete cascade,
  exercise_id uuid not null references exercises(id),
  position    int not null,
  target_sets int not null default 3
);

create table workouts (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  routine_id  uuid references routines(id),
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  note        text
);

create table workout_sets (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  workout_id  uuid not null references workouts(id) on delete cascade,
  exercise_id uuid not null references exercises(id),
  set_number  int not null,
  weight_kg   numeric(6,2) not null default 0,
  reps        int not null check (reps > 0),
  logged_at   timestamptz not null default now()
);
create index workout_sets_exercise on workout_sets (user_id, exercise_id, logged_at desc);

-- progressive-overload helper: sets from the last finished workout containing the exercise
create or replace function last_performance(p_exercise uuid)
returns table (performed_at timestamptz, set_number int, weight_kg numeric, reps int)
language sql stable as $$
  select ws.logged_at, ws.set_number, ws.weight_kg, ws.reps
  from workout_sets ws
  join workouts w on w.id = ws.workout_id and w.finished_at is not null
  where ws.exercise_id = p_exercise and ws.user_id = auth.uid()
    and w.id = (
      select w2.id from workouts w2
      join workout_sets ws2 on ws2.workout_id = w2.id
      where ws2.exercise_id = p_exercise and w2.user_id = auth.uid()
        and w2.finished_at is not null
      order by w2.started_at desc limit 1)
  order by ws.set_number;
$$;

-- ---------------------------------------------------------------- RLS
alter table profiles             enable row level security;
alter table goals                enable row level security;
alter table foods                enable row level security;
alter table food_log_entries     enable row level security;
alter table water_log_entries    enable row level security;
alter table weight_entries       enable row level security;
alter table measurement_sessions enable row level security;
alter table exercises            enable row level security;
alter table routines             enable row level security;
alter table routine_exercises    enable row level security;
alter table workouts             enable row level security;
alter table workout_sets         enable row level security;

create policy "own profile" on profiles
  for all using (id = auth.uid()) with check (id = auth.uid());

do $$
declare t text;
begin
  foreach t in array array[
    'goals','foods','food_log_entries','water_log_entries','weight_entries',
    'measurement_sessions','exercises','routines','workouts','workout_sets'
  ] loop
    execute format(
      'create policy "own rows" on %I for all using (user_id = auth.uid()) with check (user_id = auth.uid())', t);
  end loop;
end $$;

-- routine_exercises has no user_id — scope through the parent routine
create policy "own rows via routine" on routine_exercises
  for all
  using (exists (select 1 from routines r where r.id = routine_id and r.user_id = auth.uid()))
  with check (exists (select 1 from routines r where r.id = routine_id and r.user_id = auth.uid()));
