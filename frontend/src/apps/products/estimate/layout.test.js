import { describe, expect, it } from 'vitest';

import { countVerdicts, layoutOf, scaleOf, sharedScaleOf } from './layout.js';

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

  it('puts the range, its point, the label and its rounding on the track', () => {
    const { max, band, label: mark } = layoutOf(row);

    expect(max).toBeCloseTo(13.8);
    expect(band.from).toBeCloseTo((8 / 13.8) * 100);
    expect(band.to).toBeCloseTo((12 / 13.8) * 100);
    expect(band.point).toBeCloseTo((10 / 13.8) * 100);
    expect(band.open).toBe(false);
    expect(mark.at).toBeCloseTo((11 / 13.8) * 100);
    expect(mark.rounding.from).toBeCloseTo((10.5 / 13.8) * 100);
    expect(mark.rounding.to).toBeCloseTo((11.5 / 13.8) * 100);
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

  it('does not draw a rounding too narrow to be seen', () => {
    const { label: mark } = layoutOf({
      estimated: estimate('0', '50', '100'),
      declared: label('50', '50.01', '50.02'),
    });

    expect(mark.rounding).toBeNull();
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
