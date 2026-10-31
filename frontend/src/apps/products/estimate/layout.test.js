import { describe, expect, it } from 'vitest';

import {
  countVerdicts,
  factorsOf,
  layoutOf,
  placeOf,
  reliabilityOf,
  scaleOf,
  sharedScaleOf,
} from './layout.js';

const estimate = (low, point, high) => ({ low, point, high });
const label = (amount, low = amount, high = amount) => ({ amount, low, high });

describe('the track of a row', () => {
  it('holds its highest figure with a little room', () => {
    expect(
      scaleOf({ estimated: estimate('8', '10', '12'), declared: label('11') }),
    ).toBeCloseTo(12 * 1.15);
  });

  it('is made by the label when it is the highest', () => {
    expect(
      scaleOf({ estimated: estimate('1', '2', '3'), declared: label('10') }),
    ).toBeCloseTo(11.5);
  });

  it('has a good deal of room past the highest known end of an open range', () => {
    expect(
      scaleOf({ estimated: estimate('5', '6', null), declared: null }),
    ).toBeCloseTo(6 * 1.6);
  });

  it('is never zero', () => {
    expect(
      scaleOf({ estimated: estimate('0', '0', '0'), declared: null }),
    ).toBe(1);
    expect(scaleOf({ estimated: null, declared: null })).toBe(1);
  });

  it('is shared by rows that are compared, the widest of them', () => {
    const rows = [
      { estimated: estimate('0', '2', '4'), declared: null },
      { estimated: estimate('20', '30', '40'), declared: null },
    ];

    expect(sharedScaleOf(rows)).toBeCloseTo(40 * 1.15);
  });
});

describe('the marks of a row', () => {
  const row = {
    estimated: estimate('8', '10', '12'),
    declared: label('11', '10.5', '11.5'),
  };

  it('puts the range, its point and the label on the track', () => {
    const { max, band, label: mark } = layoutOf(row);

    expect(max).toBeCloseTo(13.8);
    expect(band.from).toBeCloseTo((8 / 13.8) * 100);
    expect(band.to).toBeCloseTo((12 / 13.8) * 100);
    expect(band.point).toBeCloseTo((10 / 13.8) * 100);
    expect(band.open).toBe(false);
    expect(mark.at).toBeCloseTo((11 / 13.8) * 100);
    // Its rounding is said in words, not drawn.
    expect(mark.rounding).toBeUndefined();
  });

  it('runs an open range to the end of the track', () => {
    const { band } = layoutOf({
      estimated: estimate('5', '6', null),
      declared: null,
    });

    expect(band.open).toBe(true);
    expect(band.to).toBe(100);
  });

  it('leaves out what is not there', () => {
    expect(layoutOf({ estimated: null, declared: label('3') }).band).toBeNull();
    expect(
      layoutOf({ estimated: estimate('1', '2', '3'), declared: null }).label,
    ).toBeNull();
  });

  it('gives a range as narrow as a point a width that is seen', () => {
    const { band } = layoutOf({
      estimated: estimate('5', '5', '5'),
      declared: null,
    });

    expect(band.to - band.from).toBeCloseTo(0.8, 5);
  });

  it('keeps every mark on the track', () => {
    const { band, label: mark } = layoutOf(
      { estimated: estimate('1', '2', '3'), declared: label('40') },
      10,
    );

    expect(band.to).toBeLessThanOrEqual(100);
    expect(mark.at).toBe(100);
  });

  it('draws rows on a track of the same length alike', () => {
    const a = layoutOf(
      { estimated: estimate('0', '1', '2'), declared: null },
      10,
    );
    const b = layoutOf(
      { estimated: estimate('0', '1', '2'), declared: null },
      10,
    );

    expect(a).toEqual(b);
  });
});

describe('the verdicts of a group', () => {
  it('counts each kind', () => {
    const rows = [
      { verdict: 'agrees', constrained: false },
      { verdict: 'agrees', constrained: false },
      { verdict: 'declared_below', constrained: false },
      { verdict: 'declared_above', constrained: false },
      { verdict: 'agrees', constrained: true },
      { verdict: 'not_estimated', constrained: false },
      { verdict: null, constrained: false },
    ];

    expect(countVerdicts(rows)).toEqual({
      agrees: 2,
      differs: 2,
      used: 1,
      none: 2,
    });
  });
});

describe('the room of a track', () => {
  it('holds the label, and not the tolerance around it, which is said in words', () => {
    const row = {
      estimated: estimate('13.7', '13.8', '13.9'),
      declared: {
        amount: '13',
        low: '12.5',
        high: '13.5',
        tolerance_low: '9.9',
        tolerance_high: '16.1',
      },
    };

    expect(scaleOf(row)).toBeCloseTo(13.9 * 1.15);
    expect(layoutOf(row).label).toEqual({ at: expect.any(Number) });
  });
});

describe('where a text about a mark is set', () => {
  it('is on the mark, and leans on the end it is near', () => {
    expect(placeOf(50)).toBe('centre');
    expect(placeOf(85.9)).toBe('centre');
    expect(placeOf(12)).toBe('start');
    expect(placeOf(0)).toBe('start');
    expect(placeOf(88)).toBe('end');
    expect(placeOf(100)).toBe('end');
  });
});

describe('how far to trust an estimate', () => {
  const confidence = (score, parts = {}) => ({
    score,
    coverage: '1',
    quality: '0.5',
    uncertainty: '0.1',
    agreement: null,
    ...parts,
  });

  it('is low under 0.3, average under 0.6, good from there', () => {
    expect(reliabilityOf(confidence('0.21'))).toBe(1);
    expect(reliabilityOf(confidence('0.29'))).toBe(1);
    expect(reliabilityOf(confidence('0.3'))).toBe(2);
    expect(reliabilityOf(confidence('0.59'))).toBe(2);
    expect(reliabilityOf(confidence('0.6'))).toBe(3);
    expect(reliabilityOf(confidence('0.73'))).toBe(3);
  });

  it('is nothing where there is no confidence', () => {
    expect(reliabilityOf(null)).toBeNull();
    expect(factorsOf(null)).toBeNull();
  });

  it('gives its four parts, the uncertainty as what is known of the recipe', () => {
    const factors = factorsOf(
      confidence('0.21', {
        coverage: '1',
        quality: '0.25',
        uncertainty: '0.16',
      }),
    );

    expect(factors.map(({ key }) => key)).toEqual([
      'coverage',
      'quality',
      'recipe',
      'agreement',
    ]);
    expect(factors.map(({ value }) => value)).toEqual([1, 0.25, 0.84, null]);
  });

  it('says which part holds it down the most', () => {
    const factors = factorsOf(
      confidence('0.21', {
        coverage: '0.9',
        quality: '0.25',
        uncertainty: '0.16',
      }),
    );

    expect(factors.filter((part) => part.limiting).map((p) => p.key)).toEqual([
      'quality',
    ]);
  });

  it('holds nothing down where every part is whole, or unknown', () => {
    const whole = factorsOf(
      confidence('1', { quality: '1', uncertainty: '0', agreement: '1' }),
    );

    expect(whole.some((part) => part.limiting)).toBe(false);
    // An agreement of null is no check that could have failed: not a part to rank.
    const unchecked = factorsOf(confidence('0.5', { agreement: null }));
    expect(unchecked.find((part) => part.key === 'agreement').limiting).toBe(
      false,
    );
  });
});
