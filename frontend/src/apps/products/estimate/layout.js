// Where the figures of an estimate stand on a gauge. The estimate is a range with a
// point in it and the label a value: the gauge draws them on one track from zero, and
// the page only has to put them where this says. The rounding the label is written
// with and the tolerance the European Commission allows around it are said in words
// where a row is opened, not drawn.

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
  ].filter((value) => typeof value === 'number');
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
 * - `label`, where the label's value is.
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
  const label = declared ? { at: share(Number(declared.amount), max) } : null;
  return { max, band, label };
}

// A text over or under the track is kept inside it: the nearer an end the mark is, the
// more the text leans on that end instead of being centred on the mark.
const NEAR_END = 12;

/** How a text about a mark at `position` (a share of the track) is set: which side it leans on. */
export function placeOf(position) {
  if (position <= NEAR_END) return 'start';
  if (position >= 100 - NEAR_END) return 'end';
  return 'centre';
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

// Where the scores of confidence part: under 0.3 is low, from 0.6 good.
const LOW = 0.3;
const GOOD = 0.6;

/**
 * How far to trust an estimate, as a level for a person to read: 1 low, 2 average, 3
 * good. Null where there is no confidence to read.
 */
export function reliabilityOf(confidence) {
  if (!confidence || !finite(confidence.score)) return null;
  const score = Number(confidence.score);
  if (score < LOW) return 1;
  return score < GOOD ? 2 : 3;
}

/**
 * The four parts a confidence is the product of, each between 0 and 1 (the
 * uncertainty counts as 1 minus it), with the one that holds it down the most: the
 * lowest, when it is under 1. An agreement of null is no check that could have failed,
 * which holds nothing down and is not a part to rank.
 */
export function factorsOf(confidence) {
  if (!confidence) return null;
  const parts = [
    { key: 'coverage', value: number(confidence.coverage) },
    { key: 'quality', value: number(confidence.quality) },
    {
      key: 'recipe',
      value: finite(confidence.uncertainty)
        ? 1 - Number(confidence.uncertainty)
        : null,
    },
    { key: 'agreement', value: number(confidence.agreement) },
  ];
  const ranked = parts.filter((part) => part.value !== null && part.value < 1);
  const lowest = ranked.length
    ? Math.min(...ranked.map((part) => part.value))
    : null;
  const limiting = ranked.find((part) => part.value === lowest)?.key ?? null;
  return parts.map((part) => ({ ...part, limiting: part.key === limiting }));
}
