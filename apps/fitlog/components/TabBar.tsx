"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ChartLine,
  Dumbbell,
  Droplets,
  Home,
  Plus,
  Ruler,
  Scale,
  UtensilsCrossed,
} from "lucide-react";
import { useStore, useToast } from "@/lib/store";
import { Sheet } from "./Sheet";
import { WeightSheet } from "./WeightSheet";
import { MeasureSheet } from "./MeasureSheet";
import { todayStr } from "@/lib/format";
import { uid } from "@/lib/types";

const TABS = [
  { href: "/", label: "Today", icon: Home },
  { href: "/food", label: "Food", icon: UtensilsCrossed },
  { href: "/train", label: "Train", icon: Dumbbell },
  { href: "/trends", label: "Trends", icon: ChartLine },
] as const;

export function TabBar() {
  const pathname = usePathname();
  const router = useRouter();
  const { db, update } = useStore();
  const toast = useToast();
  const [quickOpen, setQuickOpen] = useState(false);
  const [weightOpen, setWeightOpen] = useState(false);
  const [measureOpen, setMeasureOpen] = useState(false);

  const addWater = () => {
    const entry = { id: uid(), date: todayStr(), loggedAt: Date.now(), amountMl: 250 };
    update((d) => ({ ...d, water: [...d.water, entry] }));
    toast.show("+250 ml water", () =>
      update((d) => ({ ...d, water: d.water.filter((w) => w.id !== entry.id) }))
    );
    setQuickOpen(false);
  };

  const item =
    "flex flex-col items-center gap-0.5 rounded-xl px-3 py-1.5 text-[11px] font-medium";

  const actions: { label: string; icon: typeof Home; onClick: () => void }[] = [
    { label: "Add food", icon: UtensilsCrossed, onClick: () => { setQuickOpen(false); router.push("/food?add=1"); } },
    { label: "+250 ml water", icon: Droplets, onClick: addWater },
    { label: "Log weight", icon: Scale, onClick: () => { setQuickOpen(false); setWeightOpen(true); } },
    { label: "Measurements", icon: Ruler, onClick: () => { setQuickOpen(false); setMeasureOpen(true); } },
    { label: "Start workout", icon: Dumbbell, onClick: () => { setQuickOpen(false); router.push(db.activeWorkoutId ? "/train/active" : "/train"); } },
  ];

  return (
    <>
      <nav className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-bg/95 pb-[max(env(safe-area-inset-bottom),8px)] pt-2 backdrop-blur">
        <div className="mx-auto flex max-w-md items-center justify-between px-4">
          {TABS.slice(0, 2).map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href} className={`${item} ${pathname === href ? "text-ink" : "text-faint"}`}>
              <Icon size={22} strokeWidth={pathname === href ? 2.4 : 1.8} />
              {label}
            </Link>
          ))}
          <button
            aria-label="Quick add"
            onClick={() => setQuickOpen(true)}
            className="-mt-5 flex h-14 w-14 items-center justify-center rounded-full bg-accent text-white shadow-lg active:opacity-80"
          >
            <Plus size={28} />
          </button>
          {TABS.slice(2).map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(href + "/");
            return (
              <Link key={href} href={href} className={`${item} ${active ? "text-ink" : "text-faint"}`}>
                <Icon size={22} strokeWidth={active ? 2.4 : 1.8} />
                {label}
              </Link>
            );
          })}
        </div>
      </nav>

      <Sheet open={quickOpen} onClose={() => setQuickOpen(false)} title="Quick add">
        <div className="grid grid-cols-1 gap-2">
          {actions.map(({ label, icon: Icon, onClick }) => (
            <button
              key={label}
              onClick={onClick}
              className="flex h-14 items-center gap-3 rounded-2xl bg-surface2 px-4 text-left font-medium active:bg-line"
            >
              <Icon size={20} className="text-muted" />
              {label}
            </button>
          ))}
        </div>
      </Sheet>

      <WeightSheet open={weightOpen} onClose={() => setWeightOpen(false)} />
      <MeasureSheet open={measureOpen} onClose={() => setMeasureOpen(false)} />
    </>
  );
}
