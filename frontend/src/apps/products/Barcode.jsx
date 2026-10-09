import { SYMBOL_MODULES, ean13Bars } from './ean13.js';

// The empty margins a scanner needs on either side of the bars, in modules
// (the standard's 11 on the left and 7 on the right).
const QUIET_LEFT = 11;
const QUIET_RIGHT = 7;
const WIDTH = QUIET_LEFT + SYMBOL_MODULES + QUIET_RIGHT;

// Heights in modules: the guards run 4 lower than the bars, down beside the digits.
const BAR_HEIGHT = 40;
const GUARD_HEIGHT = 44;
const TEXT_BASELINE = 52;
const HEIGHT = 54;

// The digits under the bars: the leading one in the left margin, then six under
// each half (the modules the halves' bars take, without the guards).
const DIGIT_TEXTS = [
  { from: 0, to: 1, x: 5.5, length: 5 },
  { from: 1, to: 7, x: QUIET_LEFT + 3 + 21, length: 39 },
  { from: 7, to: 13, x: QUIET_LEFT + 50 + 21, length: 39 },
];

/**
 * A product's barcode as an EAN-13 symbol that a scanner can read off the screen.
 *
 * It is drawn dark on white whatever the theme is (a scanner needs the contrast,
 * and the white margins are part of the symbol). A code that is not a valid
 * EAN-13 would not scan, so it is written as plain text rather than drawn.
 *
 * @param {{ code: string, label: string, width?: number }} props `label` names
 *   the picture for screen readers ("Barcode"); `width` is in CSS pixels.
 */
export function Barcode({ code, label, width = 160 }) {
  const bars = ean13Bars(code);
  if (bars === null) {
    return <span className="text-nowrap">{code}</span>;
  }

  return (
    <svg
      role="img"
      aria-label={`${label} ${code}`}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      width={width}
      className="d-block"
    >
      <rect width={WIDTH} height={HEIGHT} fill="#fff" />
      {bars.map((bar) => (
        <rect
          key={bar.start}
          x={QUIET_LEFT + bar.start}
          width={bar.width}
          height={bar.guard ? GUARD_HEIGHT : BAR_HEIGHT}
          fill="#000"
        />
      ))}
      {DIGIT_TEXTS.map(({ from, to, x, length }) => (
        <text
          key={from}
          x={x}
          y={TEXT_BASELINE}
          fontSize="9"
          fontFamily="monospace"
          textAnchor="middle"
          textLength={length}
          lengthAdjust="spacing"
          fill="#000"
        >
          {code.slice(from, to)}
        </text>
      ))}
    </svg>
  );
}
