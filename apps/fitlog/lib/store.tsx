"use client";

// Local-first store: the whole DB lives in localStorage and every mutation is
// synchronous (optimistic by construction). The shape mirrors the Postgres
// schema so a Supabase-backed adapter can replace this without touching UI.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { DB } from "./types";
import { seedDB } from "./seed";

const STORAGE_KEY = "fitlog:v1";

interface StoreCtx {
  db: DB;
  update: (fn: (db: DB) => DB) => void;
}

const Ctx = createContext<StoreCtx | null>(null);

function migrate(raw: unknown): DB {
  const base = seedDB();
  if (!raw || typeof raw !== "object") return base;
  const d = raw as Partial<DB>;
  return {
    ...base,
    ...d,
    version: 1,
    goals: { ...base.goals, ...(d.goals ?? {}) },
    settings: { ...base.settings, ...(d.settings ?? {}) },
    foods: d.foods ?? base.foods,
    exercises: d.exercises ?? base.exercises,
    routines: d.routines ?? base.routines,
    foodEntries: d.foodEntries ?? [],
    water: d.water ?? [],
    weights: d.weights ?? [],
    measurements: d.measurements ?? [],
    workouts: d.workouts ?? [],
  };
}

export function StoreProvider({ children }: { children: ReactNode }) {
  const [db, setDb] = useState<DB | null>(null);

  useEffect(() => {
    let next: DB;
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      next = raw ? migrate(JSON.parse(raw)) : seedDB();
      if (!raw) localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      next = seedDB();
    }
    setDb(next);
  }, []);

  const update = useCallback((fn: (db: DB) => DB) => {
    setDb((prev) => {
      if (!prev) return prev;
      const next = fn(prev);
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        // storage full/unavailable — state still updates for this session
      }
      return next;
    });
  }, []);

  if (!db) {
    // First client render matches SSR output (no data yet) — avoids hydration mismatch.
    return <div className="min-h-dvh bg-bg" />;
  }
  return <Ctx.Provider value={{ db, update }}>{children}</Ctx.Provider>;
}

export function useStore(): StoreCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useStore must be used inside <StoreProvider>");
  return ctx;
}

// ---------------------------------------------------------------------------
// Toasts (with undo) — logging never blocks on a confirmation dialog.

interface Toast {
  id: number;
  message: string;
  undo?: () => void;
}

interface ToastCtxT {
  show: (message: string, undo?: () => void) => void;
}

const ToastContext = createContext<ToastCtxT | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = useCallback((message: string, undo?: () => void) => {
    if (timer.current) clearTimeout(timer.current);
    const id = Date.now();
    setToast({ id, message, undo });
    timer.current = setTimeout(() => setToast(null), 3500);
  }, []);

  return (
    <ToastContext.Provider value={{ show }}>
      {children}
      {toast && (
        <div className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex justify-center px-4">
          <div className="pointer-events-auto flex items-center gap-3 rounded-full border border-line bg-surface2 px-4 py-2 text-sm text-ink shadow-lg">
            <span>{toast.message}</span>
            {toast.undo && (
              <button
                className="font-semibold text-accent"
                onClick={() => {
                  toast.undo?.();
                  setToast(null);
                }}
              >
                Undo
              </button>
            )}
          </div>
        </div>
      )}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastCtxT {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
