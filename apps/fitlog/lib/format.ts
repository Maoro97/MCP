// Date and unit helpers. Weight is stored canonically in kg; conversion is
// display-only, driven by settings.unitWeight.

export const KG_PER_LB = 0.45359237;

export function todayStr(d: Date = new Date()): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function parseDate(dateStr: string): Date {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function addDays(dateStr: string, n: number): string {
  const d = parseDate(dateStr);
  d.setDate(d.getDate() + n);
  return todayStr(d);
}

export function fmtDay(dateStr: string): string {
  return parseDate(dateStr).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

export function fmtShort(dateStr: string): string {
  return parseDate(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

export function fmtElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(sec).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}

export function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

export function kgToUnit(kg: number, unit: "kg" | "lb"): number {
  return unit === "kg" ? kg : kg / KG_PER_LB;
}

export function unitToKg(v: number, unit: "kg" | "lb"): number {
  return unit === "kg" ? v : v * KG_PER_LB;
}

export function fmtWeight(kg: number, unit: "kg" | "lb"): string {
  return `${round1(kgToUnit(kg, unit))} ${unit}`;
}
