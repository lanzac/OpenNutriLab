// How the pages write what the server worked out, in the language it serves.

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
