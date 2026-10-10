import { describe, expect, it } from 'vitest';

import { productBarcode } from './barcode.js';

describe('productBarcode', () => {
  it('gives the EAN-13 a detector saw', () => {
    expect(productBarcode([{ rawValue: '4006381333931' }])).toBe(
      '4006381333931',
    );
  });

  it('gives a UPC-A back its leading 0', () => {
    // The textbook UPC-A, 12 digits: the same number as an EAN-13 with a 0 in front.
    expect(productBarcode([{ rawValue: '036000291452' }])).toBe(
      '0036000291452',
    );
  });

  it('leaves a code whose check digit is wrong', () => {
    expect(productBarcode([{ rawValue: '4006381333932' }])).toBeNull();
    expect(productBarcode([{ rawValue: '036000291453' }])).toBeNull();
  });

  it('leaves what is no EAN-13 or UPC-A at all', () => {
    // An EAN-8, a QR code's text, and a number too long.
    expect(productBarcode([{ rawValue: '73513537' }])).toBeNull();
    expect(productBarcode([{ rawValue: 'https://example.org' }])).toBeNull();
    expect(productBarcode([{ rawValue: '40063813339310' }])).toBeNull();
  });

  it('takes the first good code among several', () => {
    expect(
      productBarcode([
        { rawValue: 'hello' },
        { rawValue: '3229820794556' },
        { rawValue: '4006381333931' },
      ]),
    ).toBe('3229820794556');
  });

  it('gives nothing when nothing was seen', () => {
    expect(productBarcode([])).toBeNull();
  });
});
