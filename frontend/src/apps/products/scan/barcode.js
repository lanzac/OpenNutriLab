import { isEan13 } from '../ean13.js';

/**
 * The barcode of a product among what a detector saw in a picture, or null.
 *
 * A product is known by its EAN-13. A UPC-A, which a detector may report for
 * an EAN-13 that starts with 0, is the same number without that 0, so it is
 * given it back. A code whose check digit is wrong was misread, or is no
 * product's at all, and is left.
 *
 * @param {{ rawValue: string }[]} detected
 * @returns {string | null}
 */
export function productBarcode(detected) {
  for (const { rawValue } of detected) {
    const code = rawValue.length === 12 ? `0${rawValue}` : rawValue;
    if (isEan13(code)) return code;
  }
  return null;
}
