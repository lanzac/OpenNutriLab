import { describe, expect, it } from 'vitest';

import {
  formatAmount,
  formatInterval,
  formatNumber,
  kcal,
  shiftDay,
} from './format.js';

describe('formatNumber', () => {
  it('keeps three significant digits and never rounds the integer part', () => {
    expect(formatNumber('1416.07', 'en')).toBe('1,416');
    expect(formatNumber('12.3456', 'en')).toBe('12.3');
    expect(formatNumber('0.012174', 'en')).toBe('0.0122');
    expect(formatNumber(0, 'en')).toBe('0');
  });

  it('follows the language it is given', () => {
    expect(formatNumber('12.3456', 'fr-fr')).toBe('12,3');
  });

  it('writes nothing for what is not a number', () => {
    expect(formatNumber(null, 'en')).toBe('');
    expect(formatNumber(undefined, 'en')).toBe('');
    expect(formatNumber('x', 'en')).toBe('');
  });
});

describe('energy', () => {
  it('is kept in kJ and shown in kcal', () => {
    expect(kcal(4184)).toBe(1000);
    expect(formatAmount('4184', 'kJ', 'en')).toBe('1,000 kcal');
  });

  it('gives the other units as they are', () => {
    expect(formatAmount('66.268', 'g', 'en')).toBe('66.3 g');
    expect(formatAmount('1.7', 'mg', 'fr-fr')).toBe('1,7 mg');
  });
});

describe('formatInterval', () => {
  it('writes both ends, and a question mark where there is no upper end', () => {
    expect(formatInterval('9', '11', 'g', 'en')).toBe('9 – 11');
    expect(formatInterval('9', null, 'g', 'en')).toBe('9 – ?');
  });

  it('converts the energy to kcal as its amount is', () => {
    expect(formatInterval('4184', '8368', 'kJ', 'en')).toBe('1,000 – 2,000');
  });
});

describe('shiftDay', () => {
  it('moves by days across months and years', () => {
    expect(shiftDay('2026-10-09', 1)).toBe('2026-10-10');
    expect(shiftDay('2026-10-31', 1)).toBe('2026-11-01');
    expect(shiftDay('2026-01-01', -1)).toBe('2025-12-31');
    expect(shiftDay('2028-02-28', 1)).toBe('2028-02-29');
  });
});
