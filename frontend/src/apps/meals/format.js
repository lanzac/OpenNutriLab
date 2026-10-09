// How the page writes what the server worked out.

export const KJ_PER_KCAL = 4.184;

export const kcal = (kilojoules) => Number(kilojoules) / KJ_PER_KCAL;

/**
 * A figure to three significant digits, in the language Django serves. The
 * integer part is never rounded (1416.07 is 1416): amounts go from kJ to
 * fractions of a µg, so a fixed number of decimals would lose them.
 */
export function formatNumber(value, languageCode) {
  const number = Number(value);
  if (value === null || value === undefined || !Number.isFinite(number)) {
    return '';
  }
  if (number === 0) return '0';
  const options =
    Math.abs(number) >= 100
      ? { maximumFractionDigits: 0 }
      : { maximumSignificantDigits: 3 };
  return new Intl.NumberFormat(languageCode, options).format(number);
}

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

/** A share of something as the language writes a percent: 0.456 is "46 %". */
export function formatPercent(fraction, languageCode) {
  const number = Number(fraction);
  if (!Number.isFinite(number)) return '';
  return new Intl.NumberFormat(languageCode, {
    style: 'percent',
    // Under a tenth, a whole percent is too coarse to tell 0.4 % from nothing.
    maximumFractionDigits: Math.abs(number) < 0.1 ? 1 : 0,
  }).format(number);
}

/**
 * "%(name)s" and the like put in: the server translated the text and left the
 * figures, which it cannot know where they stand in another language.
 */
export const fill = (text, values) =>
  Object.entries(values).reduce(
    (found, [name, value]) => found.replace(`%(${name})s`, value),
    text,
  );
