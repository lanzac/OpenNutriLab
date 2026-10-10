// How the page writes what the server worked out.

import { fill, formatNumber, formatPercent } from '../../shared/format.js';

export { fill, formatNumber, formatPercent };

export const KJ_PER_KCAL = 4.184;

export const kcal = (kilojoules) => Number(kilojoules) / KJ_PER_KCAL;

/** "12.3 g", or "450 kcal" for the energy, which the catalogue keeps in kJ. */
export function formatAmount(value, unit, languageCode) {
  if (unit === 'kJ') {
    return `${formatNumber(kcal(value), languageCode)} kcal`;
  }
  return `${formatNumber(value, languageCode)} ${unit}`;
}

/** The interval of a total, "9 – 11", with "?" where no upper end is known. */
export function formatInterval(low, high, unit, languageCode) {
  const convert = unit === 'kJ' ? kcal : Number;
  const end = (value) =>
    value === null || value === undefined
      ? '?'
      : formatNumber(convert(value), languageCode);
  return `${end(low)} – ${end(high)}`;
}

/** The day after (or before, with a negative step) an ISO date. */
export function shiftDay(day, step) {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + step);
  return date.toISOString().slice(0, 10);
}

// A day is kept as an ISO date ("2026-10-10") and written as the language writes it:
// "10/10/2026" in French, where the order of day and month is the language's own and
// not the browser's, which is all a date field would follow.
const DAY_FORMAT = { day: '2-digit', month: '2-digit', year: 'numeric' };

const dayFormatter = (languageCode) =>
  new Intl.DateTimeFormat(languageCode, { ...DAY_FORMAT, timeZone: 'UTC' });

/** An ISO date as the language writes it, "10/10/2026" in French. */
export function formatDay(day, languageCode) {
  return dayFormatter(languageCode).format(new Date(`${day}T00:00:00Z`));
}

/**
 * A day typed in the order the language writes it back as an ISO date, or null when
 * it is none (a month of 13, a 31st of June). Any separator does, and a year of two
 * digits is of this century.
 */
export function parseDay(text, languageCode) {
  const numbers = text.trim().split(/\D+/);
  if (numbers.length !== 3 || numbers.some((n) => n === '')) return null;
  const order = dayFormatter(languageCode)
    .formatToParts(new Date(0))
    .map((part) => part.type)
    .filter((type) => ['day', 'month', 'year'].includes(type));
  const found = Object.fromEntries(
    order.map((type, index) => [type, Number(numbers[index])]),
  );
  const year = found.year < 100 ? 2000 + found.year : found.year;
  const date = new Date(Date.UTC(year, found.month - 1, found.day));
  const valid =
    date.getUTCFullYear() === year &&
    date.getUTCMonth() === found.month - 1 &&
    date.getUTCDate() === found.day;
  return valid ? date.toISOString().slice(0, 10) : null;
}

/** An ISO date ("2026-10-12") as it is, or null when the text is no day. */
export function readIsoDay(text) {
  if (typeof text !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    return null;
  }
  const date = new Date(`${text}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ||
    date.toISOString().slice(0, 10) !== text
    ? null
    : text;
}
