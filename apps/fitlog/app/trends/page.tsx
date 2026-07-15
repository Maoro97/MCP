"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Plus } from "lucide-react";
import { useStore } from "@/lib/store";
import { dayTotals, rollingAvg, weightSeries } from "@/lib/calc";
import { addDays, fmtShort, kgToUnit, parseDate, round1, todayStr } from "@/lib/format";
import { METRICS } from "@/lib/types";
import { MeasureSheet } from "@/components/MeasureSheet";
import { WeightChart, type ChartPoint } from "@/components/WeightChart";

const RANGES = [
  { key: "7d", label: "7D", days: 7 },
  { key: "30d", label: "30D", days: 30 },
  { key: "3m", label: "3M", days: 91 },
  { key: "1y", label: "1Y", days: 365 },
] as const;

const card = "rounded-[16px] border border-line bg-surface p-4";

function TrendsInner() {
  const { db } = useStore();
  const params = useSearchParams();
  const [range, setRange] = useState<(typeof RANGES)[number]>(RANGES[1]);
  const [measureOpen, setMeasureOpen] = useState(false);

  useEffect(() => {
    if (params.get("measure") === "1") setMeasureOpen(true);
  }, [params]);

  const unit = db.settings.unitWeight;
  const today = todayStr();

  const series = useMemo(() => weightSeries(db), [db]);
  const avg = useMemo(() => rollingAvg(series), [series]);
  const from = addDays(today, -(range.days - 1));
  const points: ChartPoint[] = series
    .map((e, i) => ({ date: e.date, kg: e.weightKg, avg: avg[i].avg }))
    .filter((p) => p.date >= from);

  const current = points[points.length - 1];
  const first = points[0];
  const changeKg = current && first ? current.avg - first.avg : undefined;

  // weekly averages table (last 8 weeks with data), most recent first
  const weeks = useMemo(() => {
    const byWeek = new Map<string, number[]>();
    for (const e of series) {
      const d = parseDate(e.date);
      const monday = new Date(d);
      monday.setDate(d.getDate() - ((d.getDay() + 6) % 7));
      const key = todayStr(monday);
      byWeek.set(key, [...(byWeek.get(key) ?? []), e.weightKg]);
    }
    const rows = [...byWeek.entries()]
      .sort((a, b) => (a[0] < b[0] ? 1 : -1))
      .slice(0, 8)
      .map(([weekStart, vals]) => ({
        weekStart,
        avg: vals.reduce((s, v) => s + v, 0) / vals.length,
        n: vals.length,
      }));
    return rows.map((r, i) => ({
      ...r,
      delta: i + 1 < rows.length ? r.avg - rows[i + 1].avg : undefined,
    }));
  }, [series]);

  // measurements: last 4 sessions, oldest → newest, plus change
  const sessions = useMemo(
    () => [...db.measurements].sort((a, b) => a.loggedAt - b.loggedAt).slice(-4),
    [db.measurements]
  );

  // nutrition: last 7 days of calories vs goal
  const kcalDays = useMemo(() => {
    return Array.from({ length: 7 }, (_, i) => {
      const date = addDays(today, -(6 - i));
      return { date, kcal: dayTotals(db, date).kcal };
    });
  }, [db, today]);
  const kcalMax = Math.max(db.goals.kcal, ...kcalDays.map((d) => d.kcal), 1);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Trends</h1>

      {/* Weight */}
      <section className={card}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold">Weight</h2>
          <div className="flex gap-1 rounded-full bg-surface2 p-1">
            {RANGES.map((r) => (
              <button
                key={r.key}
                onClick={() => setRange(r)}
                className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                  range.key === r.key ? "bg-ink text-bg" : "text-muted"
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>

        {points.length === 0 ? (
          <p className="py-6 text-center text-sm text-faint">
            No weigh-ins in this range yet — log one from Today.
          </p>
        ) : (
          <>
            <div className="mb-3 grid grid-cols-3 gap-2 text-center">
              <div className="rounded-xl bg-surface2 p-2">
                <div className="text-[11px] text-faint">Current</div>
                <div className="tnum font-bold">
                  {round1(kgToUnit(current.kg, unit))} {unit}
                </div>
              </div>
              <div className="rounded-xl bg-surface2 p-2">
                <div className="text-[11px] text-faint">7-day avg</div>
                <div className="tnum font-bold">
                  {round1(kgToUnit(current.avg, unit))} {unit}
                </div>
              </div>
              <div className="rounded-xl bg-surface2 p-2">
                <div className="text-[11px] text-faint">Change ({range.label})</div>
                <div className="tnum font-bold">
                  {changeKg === undefined
                    ? "—"
                    : `${changeKg <= 0 ? "▼" : "▲"} ${Math.abs(round1(kgToUnit(changeKg, unit)))}`}
                </div>
              </div>
            </div>
            <WeightChart points={points} unit={unit} />
          </>
        )}

        {weeks.length > 0 && (
          <div className="mt-4">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-faint">
              Weekly averages
            </h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-faint">
                  <th className="py-1 font-normal">Week of</th>
                  <th className="py-1 text-right font-normal">Avg ({unit})</th>
                  <th className="py-1 text-right font-normal">Δ vs prev</th>
                </tr>
              </thead>
              <tbody>
                {weeks.map((w) => (
                  <tr key={w.weekStart} className="border-t border-line">
                    <td className="py-1.5">{fmtShort(w.weekStart)}</td>
                    <td className="tnum py-1.5 text-right">{round1(kgToUnit(w.avg, unit))}</td>
                    <td className="tnum py-1.5 text-right text-muted">
                      {w.delta === undefined
                        ? "—"
                        : `${w.delta <= 0 ? "▼" : "▲"} ${Math.abs(round1(kgToUnit(w.delta, unit)))}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Measurements */}
      <section className={card}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold">Measurements</h2>
          <button
            onClick={() => setMeasureOpen(true)}
            className="flex items-center gap-1 text-sm font-medium text-accent"
          >
            <Plus size={16} /> Log
          </button>
        </div>
        {sessions.length === 0 ? (
          <p className="py-4 text-center text-sm text-faint">
            No sessions yet — measurements work best weekly or bi-weekly.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[320px] text-sm">
              <thead>
                <tr className="text-left text-xs text-faint">
                  <th className="py-1 font-normal">cm</th>
                  {sessions.map((s) => (
                    <th key={s.id} className="py-1 text-right font-normal">
                      {fmtShort(s.date)}
                    </th>
                  ))}
                  <th className="py-1 text-right font-normal">Δ</th>
                </tr>
              </thead>
              <tbody>
                {METRICS.map(({ key, label }) => {
                  const vals = sessions.map((s) => s.values[key]);
                  const present = vals.filter((v): v is number => v != null);
                  const delta =
                    present.length >= 2 ? present[present.length - 1] - present[0] : undefined;
                  return (
                    <tr key={key} className="border-t border-line">
                      <td className="py-1.5 text-muted">{label}</td>
                      {vals.map((v, i) => (
                        <td key={i} className="tnum py-1.5 text-right">
                          {v ?? "—"}
                        </td>
                      ))}
                      <td className="tnum py-1.5 text-right text-muted">
                        {delta === undefined
                          ? "—"
                          : `${delta <= 0 ? "▼" : "▲"} ${Math.abs(round1(delta))}`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Nutrition — last 7 days */}
      <section className={card}>
        <h2 className="mb-3 font-semibold">Calories — last 7 days</h2>
        {/* plot area: fixed height so bar/goal-line percentages share one scale */}
        <div className="relative mt-4 h-28">
          <div
            className="absolute inset-x-0 z-10 border-t border-dashed border-faint"
            style={{ bottom: `${(db.goals.kcal / kcalMax) * 100}%` }}
          >
            <span className="absolute -top-4 right-0 text-[10px] text-faint">
              goal {db.goals.kcal}
            </span>
          </div>
          <div className="flex h-full items-end gap-2">
            {kcalDays.map((d, i) => (
              <div
                key={d.date}
                className="relative flex h-full flex-1 flex-col items-center justify-end"
                title={`${fmtShort(d.date)}: ${Math.round(d.kcal)} kcal`}
              >
                {i === 6 && d.kcal > 0 && (
                  <span className="tnum mb-0.5 text-[10px] text-muted">{Math.round(d.kcal)}</span>
                )}
                <div
                  className="w-full rounded-t"
                  style={{
                    height: `${Math.max((d.kcal / kcalMax) * 100, d.kcal > 0 ? 2 : 0.5)}%`,
                    background:
                      i === 6
                        ? "var(--color-cal)"
                        : "color-mix(in oklab, var(--color-cal) 55%, var(--color-surface2))",
                  }}
                />
              </div>
            ))}
          </div>
        </div>
        <div className="mt-1 flex gap-2">
          {kcalDays.map((d) => (
            <span key={d.date} className="flex-1 text-center text-[10px] text-faint">
              {parseDate(d.date).toLocaleDateString("en-US", { weekday: "narrow" })}
            </span>
          ))}
        </div>
      </section>

      <MeasureSheet open={measureOpen} onClose={() => setMeasureOpen(false)} />
    </div>
  );
}

export default function TrendsPage() {
  return (
    <Suspense fallback={null}>
      <TrendsInner />
    </Suspense>
  );
}
