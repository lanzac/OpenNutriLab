import { describe, expect, it } from 'vitest';

import { convertDeclared, convertRange } from './convert.js';

// An oil: a millilitre of it weighs 0.908 to 0.915 g.
const density = { low: '0.908', point: '0.9115', high: '0.915' };

describe('an estimate per 100 g shown per 100 ml', () => {
  it('multiplies each end by the density that makes the range widest', () => {
    const found = convertRange(
      { low: '99.85', point: '99.9', high: '99.95' },
      density,
      'g',
      'ml',
    );

    expect(found.low).toBeCloseTo(99.85 * 0.908);
    expect(found.point).toBeCloseTo(99.9 * 0.9115);
    expect(found.high).toBeCloseTo(99.95 * 0.915);
  });

  it('leaves an open range open', () => {
    const found = convertRange(
      { low: '1', point: '2', high: null },
      density,
      'g',
      'ml',
    );

    expect(found.high).toBeNull();
    expect(found.low).toBeCloseTo(0.908);
  });
});

describe('a figure per 100 ml shown per 100 g', () => {
  it('divides by the density, the low end by the heaviest millilitre', () => {
    const found = convertRange(
      { low: '90', point: '91', high: '92' },
      density,
      'ml',
      'g',
    );

    expect(found.low).toBeCloseTo(90 / 0.915);
    expect(found.point).toBeCloseTo(91 / 0.9115);
    expect(found.high).toBeCloseTo(92 / 0.908);
  });

  it('round-trips into a range that holds the one it came from', () => {
    const start = { low: '90', point: '91', high: '92' };

    const back = convertRange(
      convertRange(start, density, 'ml', 'g'),
      density,
      'g',
      'ml',
    );

    expect(back.point).toBeCloseTo(91);
    expect(back.low).toBeLessThanOrEqual(90);
    expect(back.high).toBeGreaterThanOrEqual(92);
  });
});

describe('what is left as it is', () => {
  const range = { low: '1', point: '2', high: '3' };

  it('a figure already in the unit asked for', () => {
    expect(convertRange(range, density, 'g', 'g')).toBe(range);
  });

  it('a figure with no density to convert it with', () => {
    expect(convertRange(range, null, 'g', 'ml')).toBe(range);
  });

  it('nothing', () => {
    expect(convertRange(null, density, 'g', 'ml')).toBeNull();
    expect(convertDeclared(null, density, 'ml', 'g')).toBeNull();
  });
});

describe('the label shown in the other unit', () => {
  const declared = {
    amount: '91',
    low: '90.5',
    high: '91.5',
    tolerance_low: '82.5',
    tolerance_high: '99.5',
  };

  it('converts the figure, its rounding and its tolerance', () => {
    const found = convertDeclared(declared, density, 'ml', 'g');

    expect(found.amount).toBeCloseTo(91 / 0.9115);
    expect(found.low).toBeCloseTo(90.5 / 0.915);
    expect(found.high).toBeCloseTo(91.5 / 0.908);
    expect(found.tolerance_low).toBeCloseTo(82.5 / 0.915);
    expect(found.tolerance_high).toBeCloseTo(99.5 / 0.908);
  });

  it('keeps a missing tolerance missing', () => {
    const found = convertDeclared(
      { amount: '91', low: '90.5', high: '91.5' },
      density,
      'ml',
      'g',
    );

    expect(found.tolerance_low).toBeNull();
    expect(found.tolerance_high).toBeNull();
  });

  it('converts a label given per 100 g to per 100 ml the other way', () => {
    const found = convertDeclared(
      { amount: '100', low: '99.5', high: '100.5' },
      density,
      'g',
      'ml',
    );

    expect(found.amount).toBeCloseTo(100 * 0.9115);
    expect(found.low).toBeCloseTo(99.5 * 0.908);
    expect(found.high).toBeCloseTo(100.5 * 0.915);
  });
});
