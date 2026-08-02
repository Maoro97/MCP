/**
 * עיצוב ערכים לתצוגה.
 *
 * הכלל היחיד שאסור לשבור: ערך חסר מוצג כ"— לא התקבל", **לעולם לא כאפס**.
 * הצגת חוסר כאפס היא בדיוק התקלה שמטעה סוכנים במערכות הקיימות: דמי ניהול
 * שלא דווחו נראים כמו דמי ניהול אפס, והסוכן ממליץ על סמך נתון שלא קיים.
 */

export const MISSING = '— לא התקבל';

const shekel = new Intl.NumberFormat('he-IL', {
  style: 'currency',
  currency: 'ILS',
  maximumFractionDigits: 0,
});

export function money(value: number | null | undefined): string {
  return value === null || value === undefined ? MISSING : shekel.format(value);
}

export function pct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return MISSING;
  return `${Number(value.toFixed(digits))}%`;
}

export function ratio(value: number | null | undefined): string {
  if (value === null || value === undefined) return MISSING;
  return `${Math.round(value * 100)}%`;
}

export function hebrewDate(value: string | null | undefined): string {
  if (!value) return MISSING;
  return new Intl.DateTimeFormat('he-IL', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(new Date(value));
}

export function isMissing(value: unknown): boolean {
  return value === null || value === undefined;
}

/** האם התאריך נופל בתוך N החודשים הקרובים (להתראת סיום הטבה). */
export function withinMonths(date: string | null, months: number): boolean {
  if (!date) return false;
  const limit = new Date();
  limit.setMonth(limit.getMonth() + months);
  return new Date(date) <= limit;
}
