// Where the figures of an estimate stand on a gauge. The estimate is a range with a
// point in it, the label a value with the rounding it is written with: the gauge draws
// both on one track from zero, and the page only has to put them where this says.

// Room left above the highest figure, and, where the range has no upper end, past the
// highest known one, for the open end of it to be seen.
const ROOM = 1.15;
const ROOM_WHEN_OPEN = 1.6;
// A mark narrower than this (as a share of the track) is not seen.
const LEAST_WIDTH = 0.8;

const finite = (value) =>
  value !== null && value !== undefined && Number.isFinite(Number(value));
const number = (value) => (finite(value) ? Number(value) : null);

/** The highest figure of a row, which its track is made to hold. */
function topOf({ estimated, declared }) {
  const figures = [
    estimated && number(estimated.high),
    estimated && number(estimated.point),
    estimated && number(estimated.low),
    declared && number(declared.amount),
    declared && number(declared.high),
  ].filter((value) => value !== null);
  return figures.length === 0 ? 0 : Math.max(...figures);
}

const isOpen = (estimated) => Boolean(estimated) && !finite(estimated.high);

/**
 * The end of the track of one row: a little over its highest figure, or a good deal
 * over it when the estimate has no upper end. Never zero.
 */
export function scaleOf(row) {
  const top = topOf(row);
  const max = top * (isOpen(row.estimated) ? ROOM_WHEN_OPEN : ROOM);
  return max > 0 ? max : 1;
}

/** One track for rows that are compared with each other (the shares of a recipe). */
export function sharedScaleOf(rows) {
  return Math.max(...rows.map(scaleOf), 1e-9);
}

const share = (value, max) => Math.min(Math.max((value / max) * 100, 0), 100);

/**
 * Where each mark goes, as a share of the track:
 * - `band`, the range of the estimate, open when it has no upper end, and `point`;
 * - `label`, the label's value, and `rounding`, the range it stands for.
 * Either is null where there is none. `max` is the end of the track; by default the
 * row's own.
 */
export function layoutOf(
  { estimated, declared },
  max = scaleOf({ estimated, declared }),
) {
  let band = null;
  if (estimated) {
    const from = share(Number(estimated.low), max);
    const open = isOpen(estimated);
    const to = open ? 100 : share(Number(estimated.high), max);
    band = {
      from,
      to: Math.max(to, Math.min(from + LEAST_WIDTH, 100)),
      open,
      point: share(Number(estimated.point), max),
    };
  }
  let label = null;
  if (declared) {
    const at = share(Number(declared.amount), max);
    const from = share(Number(declared.low), max);
    const to = share(Number(declared.high), max);
    label = {
      at,
      // What the label's rounding covers, when it is wide enough to be seen.
      rounding: to - from >= LEAST_WIDTH ? { from, to } : null,
    };
  }
  return { max, band, label };
}

/** How many nutrients of each kind of verdict a group holds, for its head. */
export function countVerdicts(rows) {
  const counts = { agrees: 0, differs: 0, used: 0, none: 0 };
  for (const row of rows) {
    if (row.constrained) counts.used += 1;
    else if (row.verdict === 'agrees') counts.agrees += 1;
    else if (
      row.verdict === 'declared_below' ||
      row.verdict === 'declared_above'
    ) {
      counts.differs += 1;
    } else counts.none += 1;
  }
  return counts;
}
