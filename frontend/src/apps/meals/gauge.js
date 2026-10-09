// Where things stand on a gauge: a nutrient's day set against what is expected.
//
// A gauge is a track, from nothing to a maximum chosen to show what matters:
//   - the zone expected (between the lowest and the highest wanted, or from the
//     lowest on, or up to the highest);
//   - the amount, as a bar from the start;
//   - the range the amount can be in (its low and high ends), as a line, which is
//     open at the far end when no upper end is known;
//   - a tick at each end of what is wanted.
// Everything is a share of the track, from 0 to 100.

// The track shows this much beyond what is wanted when the day is not past it.
const ROOM_ABOVE_HIGH = 1.35;
const ROOM_ABOVE_LOW = 1.6;
// A day far past what is wanted is shown at the end of the track, not by making the
// zone expected too thin to see: the scale is at most this many times the reference.
const MOST_TIMES_REFERENCE = 3;
const MARGIN = 1.06;

const number = (value) =>
  value === null || value === undefined ? null : Number(value);

/**
 * The layout of a gauge, as shares of the track (0 to 100).
 *
 * `amount` is the point value, `low` and `high` the ends of the range it can be in
 * (`high` is null when none is known), `needLow` and `needHigh` what is wanted (each
 * may be null).
 */
export function layoutOf({ amount, low, high, needLow, needHigh }) {
  const value = number(amount) ?? 0;
  const lowest = number(low) ?? value;
  const highest = number(high);
  const wantedLow = number(needLow);
  const wantedHigh = number(needHigh);
  const reference = wantedHigh ?? wantedLow ?? Math.max(value, 1);

  const base = wantedHigh
    ? wantedHigh * ROOM_ABOVE_HIGH
    : (wantedLow ?? reference) * ROOM_ABOVE_LOW;
  const wanted = Math.max(base, value * MARGIN, (highest ?? 0) * MARGIN);
  const max = Math.min(wanted, reference * MOST_TIMES_REFERENCE);

  const at = (position) => Math.min(100, Math.max(0, (position / max) * 100));
  const zoneFrom = wantedLow ?? 0;
  const zoneTo = wantedHigh ?? max;

  // What the day is set against: the lowest wanted, else the highest allowed.
  const against = wantedLow ?? wantedHigh;
  return {
    max,
    fill: at(value),
    overflow: value > max,
    zone: { from: at(zoneFrom), to: at(zoneTo) },
    interval: {
      from: at(lowest),
      to: highest === null ? 100 : at(highest),
      open: highest === null,
      // A range too narrow to see is still shown as a mark.
      outside: lowest > max,
    },
    ticks: [wantedLow, wantedHigh]
      .filter((end) => end !== null)
      .map((end) => ({ at: at(end), value: end })),
    // The share of what is wanted that the amount is: of the lowest, else of the
    // highest, and which of the two it is.
    share: against ? value / against : null,
    against: wantedLow !== null ? 'low' : wantedHigh !== null ? 'high' : null,
  };
}

/** How many of each status there are, for the bar that sums a day up. */
export function countStatuses(rows) {
  const counts = { within: 0, below: 0, above: 0, unknown: 0 };
  for (const row of rows) counts[row.status] += 1;
  return counts;
}
