import { describe, expect, it } from 'vitest';

import { SYMBOL_MODULES, ean13Bars, ean13Modules, isEan13 } from './ean13.js';

// One code per leading digit (which picks how the left half is written), with
// the modules a barcode scanner (zxing) read back as that very code.
const SCANNED = [
  [
    '0636966187877',
    '10101011110111101010111100010110101111010111101010110011010010001000100100100010001001000100101',
  ],
  [
    '1371522788141',
    '10101111010111011011001101100010011011001101101010100010010010001001000110011010111001100110101',
  ],
  [
    '2732398448116',
    '10101110110111101001101101000010001011000100101010101110010111001001000110011011001101010000101',
  ],
  [
    '3335947248831',
    '10101111010111101011100100101110011101011101101010110110010111001001000100100010000101100110101',
  ],
  [
    '4587150636236',
    '10101100010001001011101100110010111001010011101010101000010000101010000110110010000101010000101',
  ],
  [
    '5449402160229',
    '10101000110011101001011101000110001101001101101010110011010100001110010110110011011001110100101',
  ],
  [
    '6428458660548',
    '10101000110011011000100100111010110001011011101010101000010100001110010100111010111001001000101',
  ],
  [
    '7562492596063',
    '10101100010000101001001100111010001011001101101010100111011101001010000111001010100001000010101',
  ],
  [
    '8638627941561',
    '10101011110100001011011100001010011011011101101010111010010111001100110100111010100001100110101',
  ],
  [
    '9856090248386',
    '10101101110111001000010100011010010111000110101010110110010111001001000100001010010001010000101',
  ],
];

describe('isEan13', () => {
  it('accepts 13 digits whose last one is the check digit', () => {
    expect(isEan13('3229820794556')).toBe(true);
    expect(isEan13('4006381333931')).toBe(true);
  });

  it('refuses a wrong check digit, a wrong length and anything but digits', () => {
    expect(isEan13('3229820794557')).toBe(false);
    expect(isEan13('322982079455')).toBe(false);
    expect(isEan13('32298207945560')).toBe(false);
    expect(isEan13('322982079455X')).toBe(false);
    expect(isEan13('')).toBe(false);
  });
});

describe('ean13Modules', () => {
  it.each(SCANNED)('writes %s as a scanner reads it', (code, modules) => {
    expect(ean13Modules(code)).toBe(modules);
  });

  it('is 95 modules between the guards, whatever the code', () => {
    for (const [code] of SCANNED) {
      const modules = ean13Modules(code);
      expect(modules).toHaveLength(SYMBOL_MODULES);
      expect(modules.slice(0, 3)).toBe('101');
      expect(modules.slice(45, 50)).toBe('01010');
      expect(modules.slice(92)).toBe('101');
    }
  });

  it('has nothing to draw for what is not an EAN-13', () => {
    expect(ean13Modules('1234567890123')).toBeNull();
    expect(ean13Modules('abc')).toBeNull();
  });
});

describe('ean13Bars', () => {
  it('joins the dark modules that touch into one bar', () => {
    const modules = ean13Modules('3229820794556');
    const bars = ean13Bars('3229820794556');

    const dark = bars.reduce((n, bar) => n + bar.width, 0);
    expect(dark).toBe([...modules].filter((m) => m === '1').length);
    for (const bar of bars) {
      expect(modules.slice(bar.start, bar.start + bar.width)).toBe(
        '1'.repeat(bar.width),
      );
      // A bar ends where a gap begins.
      expect(modules[bar.start + bar.width]).not.toBe('1');
    }
  });

  it('marks the three guards, and only them, as the lower bars', () => {
    const guards = ean13Bars('3229820794556').filter((bar) => bar.guard);

    expect(guards.map((bar) => bar.start)).toEqual([0, 2, 46, 48, 92, 94]);
  });

  it('has nothing to draw for what is not an EAN-13', () => {
    expect(ean13Bars('1234567890123')).toBeNull();
  });
});
