"use client";

import { useMemo, useRef, useState } from "react";
import { fmtShort, kgToUnit, round1 } from "@/lib/format";

export interface ChartPoint {
  date: string;
  kg: number;
  avg: number;
}

/**
 * Weight trend: daily weigh-ins (muted markers + thin line) and the 7-day
 * rolling average (accent 2px line). Crosshair + tooltip on hover/touch;
 * legend above (2 series); the weekly table next to it is the table view.
 */
export function WeightChart({ points, unit }: { points: ChartPoint[]; unit: "kg" | "lb" }) {
  const W = 360;
  const H = 190;
  const PAD = { l: 34, r: 10, t: 10, b: 22 };
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const { xs, yRaw, yAvg, ticks } = useMemo(() => {
    const n = points.length;
    const vals = points.flatMap((p) => [p.kg, p.avg]).map((v) => kgToUnit(v, unit));
    let lo = Math.min(...vals);
    let hi = Math.max(...vals);
    if (hi - lo < 1) {
      lo -= 0.5;
      hi += 0.5;
    }
    const pad = (hi - lo) * 0.12;
    lo -= pad;
    hi += pad;
    const x = (i: number) =>
      n === 1 ? (PAD.l + W - PAD.r) / 2 : PAD.l + (i / (n - 1)) * (W - PAD.l - PAD.r);
    const y = (v: number) => PAD.t + (1 - (v - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
    const step = (hi - lo) / 3;
    const tk = [0, 1, 2, 3].map((i) => lo + i * step);
    return {
      xs: points.map((_, i) => x(i)),
      yRaw: points.map((p) => y(kgToUnit(p.kg, unit))),
      yAvg: points.map((p) => y(kgToUnit(p.avg, unit))),
      ticks: tk.map((v) => ({ v: round1(v), y: y(v) })),
    };
  }, [points, unit]);

  if (points.length === 0) return null;

  const path = (ys: number[]) =>
    ys.map((y, i) => `${i === 0 ? "M" : "L"}${xs[i].toFixed(1)},${y.toFixed(1)}`).join(" ");

  const onMove = (clientX: number) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const px = ((clientX - rect.left) / rect.width) * W;
    let best = 0;
    let bestD = Infinity;
    xs.forEach((x, i) => {
      const d = Math.abs(x - px);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    setHover(best);
  };

  const h = hover !== null ? points[hover] : null;

  return (
    <div>
      {/* legend — 2 series, identity never color-alone */}
      <div className="mb-1 flex gap-4 text-xs text-muted">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 rounded" style={{ background: "var(--color-protein)" }} />
          7-day average
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-faint" />
          Daily weigh-in
        </span>
      </div>
      <div className="relative">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          className="w-full touch-none select-none"
          role="img"
          aria-label={`Weight trend, ${points.length} weigh-ins`}
          onPointerMove={(e) => onMove(e.clientX)}
          onPointerLeave={() => setHover(null)}
        >
          {/* gridlines + y labels */}
          {ticks.map((t, i) => (
            <g key={i}>
              <line x1={PAD.l} x2={W - PAD.r} y1={t.y} y2={t.y} stroke="var(--color-line)" strokeWidth={1} />
              <text x={PAD.l - 6} y={t.y + 3} textAnchor="end" fontSize={9} fill="var(--color-faint)">
                {t.v}
              </text>
            </g>
          ))}
          {/* x labels: first / mid / last */}
          {[0, Math.floor((points.length - 1) / 2), points.length - 1]
            .filter((v, i, a) => a.indexOf(v) === i)
            .map((i) => (
              <text
                key={i}
                x={xs[i]}
                y={H - 6}
                textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"}
                fontSize={9}
                fill="var(--color-faint)"
              >
                {fmtShort(points[i].date)}
              </text>
            ))}
          {/* daily series: thin muted line + small markers */}
          <path d={path(yRaw)} fill="none" stroke="var(--color-faint)" strokeWidth={1} opacity={0.6} />
          {xs.map((x, i) => (
            <circle key={i} cx={x} cy={yRaw[i]} r={2} fill="var(--color-faint)" />
          ))}
          {/* 7-day average: the primary mark */}
          <path
            d={path(yAvg)}
            fill="none"
            stroke="var(--color-protein)"
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
          {/* crosshair + hover markers (2px surface ring) */}
          {hover !== null && (
            <g>
              <line
                x1={xs[hover]}
                x2={xs[hover]}
                y1={PAD.t}
                y2={H - PAD.b}
                stroke="var(--color-faint)"
                strokeWidth={1}
                strokeDasharray="3 3"
              />
              <circle cx={xs[hover]} cy={yAvg[hover]} r={4} fill="var(--color-protein)" stroke="var(--color-surface)" strokeWidth={2} />
              <circle cx={xs[hover]} cy={yRaw[hover]} r={3.5} fill="var(--color-faint)" stroke="var(--color-surface)" strokeWidth={2} />
            </g>
          )}
        </svg>
        {h && (
          <div className="pointer-events-none absolute left-1/2 top-0 -translate-x-1/2 rounded-lg border border-line bg-surface2 px-2.5 py-1.5 text-xs shadow">
            <div className="font-medium">{fmtShort(h.date)}</div>
            <div className="tnum text-muted">
              {round1(kgToUnit(h.kg, unit))} {unit} · avg {round1(kgToUnit(h.avg, unit))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
