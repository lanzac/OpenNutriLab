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
