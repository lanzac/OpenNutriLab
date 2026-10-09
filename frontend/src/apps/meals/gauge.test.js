import { describe, expect, it } from 'vitest';

import { countStatuses, layoutOf } from './gauge.js';

const near = (value, expected) => expect(value).toBeCloseTo(expected, 5);

describe('layoutOf', () => {
  it('puts the zone from the lowest wanted to the highest, and the amount as a bar', () => {
    // 66 to 133 wanted, 43.7 reached: the scale is 133 x 1.35.
    const layout = layoutOf({
      amount: '43.7',
      low: '42.7',
      high: '44.7',
      needLow: '66.3',
      needHigh: '132.5',
    });

    near(layout.max, 132.5 * 1.35);
    near(layout.zone.from, (66.3 / layout.max) * 100);
    near(layout.zone.to, (132.5 / layout.max) * 100);
    near(layout.fill, (43.7 / layout.max) * 100);
    expect(layout.overflow).toBe(false);
    expect(layout.ticks.map((tick) => tick.value)).toEqual([66.3, 132.5]);
  });

  it('shows the range the amount can be in, closed when the high end is known', () => {
    const layout = layoutOf({
      amount: 10,
      low: 8,
      high: 12,
      needLow: 10,
      needHigh: null,
    });

    near(layout.interval.from, (8 / layout.max) * 100);
    near(layout.interval.to, (12 / layout.max) * 100);
    expect(layout.interval.open).toBe(false);
  });

  it('leaves the range open to the end of the track when no high end is known', () => {
    const layout = layoutOf({
      amount: 10,
      low: 8,
      high: null,
      needLow: 30,
      needHigh: null,
    });

    expect(layout.interval.open).toBe(true);
    expect(layout.interval.to).toBe(100);
    near(layout.interval.from, (8 / layout.max) * 100);
  });

  it('has the zone run to the end of the track when only a lowest is wanted', () => {
    const layout = layoutOf({
      amount: 5,
      low: 5,
      high: 5,
      needLow: 30,
      needHigh: null,
    });

    near(layout.max, 30 * 1.6);
    expect(layout.zone.to).toBe(100);
    near(layout.zone.from, (30 / 48) * 100);
    expect(layout.ticks).toHaveLength(1);
  });

  it('has the zone start at nothing when only a highest is allowed', () => {
    const layout = layoutOf({
      amount: 2000,
      low: 1800,
      high: 2200,
      needLow: null,
      needHigh: 2300,
    });

    expect(layout.zone.from).toBe(0);
    near(layout.zone.to, (2300 / layout.max) * 100);
    expect(layout.against).toBe('high');
    near(layout.share, 2000 / 2300);
  });

  it('measures a day against the lowest wanted, else the highest', () => {
    const both = layoutOf({
      amount: 33,
      low: 33,
      high: 33,
      needLow: 66,
      needHigh: 133,
    });
    const only = layoutOf({
      amount: 33,
      low: 33,
      high: 33,
      needLow: null,
      needHigh: 66,
    });

    expect(both.against).toBe('low');
    near(both.share, 0.5);
    expect(only.against).toBe('high');
    near(only.share, 0.5);
  });

  it('grows the scale to show an amount past what is wanted', () => {
    const layout = layoutOf({
      amount: 160,
      low: 150,
      high: 170,
      needLow: null,
      needHigh: 100,
    });

    near(layout.max, 170 * 1.06);
    expect(layout.fill).toBeLessThan(100);
    expect(layout.overflow).toBe(false);
  });

  it('caps the scale at three times what is wanted, and says the amount is past it', () => {
    // 20.8 g of chloride for a need of 2.3 g: the zone would be a hair.
    const layout = layoutOf({
      amount: 20.8,
      low: 0.5,
      high: null,
      needLow: 2.3,
      needHigh: null,
    });

    near(layout.max, 2.3 * 3);
    expect(layout.fill).toBe(100);
    expect(layout.overflow).toBe(true);
    // The zone is still a part of the track that can be seen.
    expect(layout.zone.to - layout.zone.from).toBeGreaterThan(50);
  });

  it('shows an amount of nothing as an empty bar, and tolerates what is not known', () => {
    const layout = layoutOf({
      amount: 0,
      low: 0,
      high: null,
      needLow: 15,
      needHigh: 100,
    });

    expect(layout.fill).toBe(0);
    expect(
      layoutOf({
        amount: null,
        low: null,
        high: null,
        needLow: 5,
        needHigh: null,
      }).fill,
    ).toBe(0);
  });

  it('gives no share for what nothing is wanted of', () => {
    const layout = layoutOf({
      amount: 3,
      low: 3,
      high: 3,
      needLow: null,
      needHigh: null,
    });

    expect(layout.share).toBeNull();
    expect(layout.against).toBeNull();
    expect(layout.ticks).toEqual([]);
  });
});

describe('countStatuses', () => {
  it('counts each status', () => {
    const counts = countStatuses([
      { status: 'within' },
      { status: 'within' },
      { status: 'below' },
      { status: 'unknown' },
    ]);

    expect(counts).toEqual({ within: 2, below: 1, above: 0, unknown: 1 });
  });
});
