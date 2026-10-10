import { describe, expect, it } from 'vitest';

import {
  formatAmount,
  formatDay,
  formatInterval,
  formatNumber,
  kcal,
  parseDay,
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

describe('formatDay', () => {
  it('writes the day first in French and the month first in English', () => {
    expect(formatDay('2026-10-09', 'fr')).toBe('09/10/2026');
    expect(formatDay('2026-10-09', 'fr-fr')).toBe('09/10/2026');
    expect(formatDay('2026-01-05', 'fr-fr')).toBe('05/01/2026');
    expect(formatDay('2026-10-09', 'en-us')).toBe('10/09/2026');
  });

  it('does not move with the time zone of the machine', () => {
    expect(formatDay('2026-12-31', 'fr-fr')).toBe('31/12/2026');
    expect(formatDay('2026-01-01', 'fr-fr')).toBe('01/01/2026');
  });
});

describe('parseDay', () => {
  it('reads a day in the order the language writes it', () => {
    expect(parseDay('09/10/2026', 'fr-fr')).toBe('2026-10-09');
    expect(parseDay('10/09/2026', 'en-us')).toBe('2026-10-09');
  });

  it('takes any separator, and a year of two digits as of this century', () => {
    expect(parseDay('9.10.26', 'fr-fr')).toBe('2026-10-09');
    expect(parseDay(' 9-1-2027 ', 'fr-fr')).toBe('2027-01-09');
  });

  it('gives nothing for what is no day', () => {
    expect(parseDay('31/06/2026', 'fr-fr')).toBeNull();
    expect(parseDay('29/02/2027', 'fr-fr')).toBeNull();
    expect(parseDay('12/13/2026', 'fr-fr')).toBeNull();
    expect(parseDay('1/2', 'fr-fr')).toBeNull();
    expect(parseDay('', 'fr-fr')).toBeNull();
    expect(parseDay('demain', 'fr-fr')).toBeNull();
  });

  it('gives back a leap day', () => {
    expect(parseDay('29/02/2028', 'fr-fr')).toBe('2028-02-29');
  });

  it('is the other way of formatDay', () => {
    for (const language of ['fr-fr', 'en-us']) {
      expect(parseDay(formatDay('2026-03-04', language), language)).toBe(
        '2026-03-04',
      );
    }
  });
});
