// Converting the figures of an estimate between "per 100 g" and "per 100 ml", with the
// density of the product (g/ml, a range: see percentage_estimation.product_density).
//
// The estimate is worked out per 100 g, and a label can be given per 100 ml. Neither is
// changed where it is kept: this is only how the page shows them, so that the two can be
// read in the unit the person prefers. The ends of a range are converted with the ends
// of the density that make it widest, as the server does to set them against each other
// (estimate_validation._per_volume), so the range is never narrower than the truth.

/** What a figure per 100 `from` is multiplied by to be per 100 `to`, at each end. */
function factors(density, from) {
  const low = Number(density.low);
  const point = Number(density.point);
  const high = Number(density.high);
  // Per 100 g to per 100 ml: a millilitre weighs the density, so 100 ml hold more.
  if (from === 'g') return { low, point, high };
  return { low: 1 / high, point: 1 / point, high: 1 / low };
}

const times = (value, factor) =>
  value === null || value === undefined ? null : Number(value) * factor;

const converts = (value, density, from, to) =>
  Boolean(value) && Boolean(density) && from !== to;

/**
 * A range ({ low, point, high }, the high end possibly null) per 100 `from`, as one
 * per 100 `to`. Left as it is when there is nothing to convert or no density.
 */
export function convertRange(range, density, from, to) {
  if (!converts(range, density, from, to)) return range;
  const by = factors(density, from);
  return {
    low: times(range.low, by.low),
    point: times(range.point, by.point),
    high: times(range.high, by.high),
  };
}

/**
 * What the label declares ({ amount, low, high, tolerance_low, tolerance_high }), given
 * per 100 `from`, as it would be per 100 `to`.
 */
export function convertDeclared(declared, density, from, to) {
  if (!converts(declared, density, from, to)) return declared;
  const by = factors(density, from);
  return {
    amount: times(declared.amount, by.point),
    low: times(declared.low, by.low),
    high: times(declared.high, by.high),
    tolerance_low: times(declared.tolerance_low, by.low),
    tolerance_high: times(declared.tolerance_high, by.high),
  };
}
