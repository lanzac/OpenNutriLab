// EAN-13 as bars, so that the barcode a product is known by can be drawn and
// scanned from the screen without a library: the encoding is a fixed table
// (ISO/IEC 15420), the barcode field of the model is the number it encodes.
//
// A symbol is 95 modules wide: start guard, six digits from the left set,
// centre guard, six digits from the right set, end guard. The leading digit has
// no bars of its own: it picks which of the two left sets (L or G) each of the
// six digits after it is written in.

// The left set, odd parity ("L"). The right set is its complement and the
// left set, even parity ("G"), is the right set read backwards.
const L = [
  '0001101',
  '0011001',
  '0010011',
  '0111101',
  '0100011',
  '0110001',
  '0101111',
  '0111011',
  '0110111',
  '0001011',
];
const complement = (bits) =>
  [...bits].map((bit) => (bit === '1' ? '0' : '1')).join('');
const R = L.map(complement);
const G = R.map((bits) => [...bits].reverse().join(''));

// Which set the six digits after the leading one are written in.
const PARITY = [
  'LLLLLL',
  'LLGLGG',
  'LLGGLG',
  'LLGGGL',
  'LGLLGG',
  'LGGLLG',
  'LGGGLL',
  'LGLGLG',
  'LGLGGL',
  'LGGLGL',
];

const START_GUARD = '101';
const CENTRE_GUARD = '01010';
const END_GUARD = '101';

/** Width of a symbol in modules, without its quiet zones. */
export const SYMBOL_MODULES = 95;

/** True for 13 digits whose last one is the check digit of the twelve before. */
export function isEan13(code) {
  if (!/^\d{13}$/.test(code)) return false;
  const digits = [...code].map(Number);
  const sum = digits
    .slice(0, 12)
    .reduce((total, digit, i) => total + (i % 2 === 0 ? digit : digit * 3), 0);
  return (10 - (sum % 10)) % 10 === digits[12];
}

/**
 * The 95 modules of a barcode, left to right, '1' for a bar and '0' for a gap;
 * null when `code` is not a valid EAN-13 (a barcode that would not scan is not
 * drawn).
 */
export function ean13Modules(code) {
  if (!isEan13(code)) return null;
  const digits = [...code].map(Number);
  const sets = PARITY[digits[0]];
  const left = digits
    .slice(1, 7)
    .map((digit, i) => (sets[i] === 'L' ? L[digit] : G[digit]))
    .join('');
  const right = digits
    .slice(7)
    .map((digit) => R[digit])
    .join('');
  return START_GUARD + left + CENTRE_GUARD + right + END_GUARD;
}

/**
 * The bars of a barcode as runs of dark modules: `start` and `width` in
 * modules, and `guard` for the three that run lower than the rest (the start,
 * centre and end guards, which stand beside the digits' text instead of above
 * it).
 */
export function ean13Bars(code) {
  const modules = ean13Modules(code);
  if (modules === null) return null;
  const guards = [
    [0, START_GUARD.length],
    [45, CENTRE_GUARD.length],
    [92, END_GUARD.length],
  ];
  const bars = [];
  for (let i = 0; i < modules.length; i += 1) {
    if (modules[i] !== '1') continue;
    const previous = bars[bars.length - 1];
    if (previous && previous.start + previous.width === i) {
      previous.width += 1;
    } else {
      bars.push({ start: i, width: 1 });
    }
  }
  return bars.map((bar) => ({
    ...bar,
    guard: guards.some(
      ([from, length]) => bar.start >= from && bar.start < from + length,
    ),
  }));
}
