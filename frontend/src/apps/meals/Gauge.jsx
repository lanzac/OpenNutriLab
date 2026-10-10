import './gauge.css';

import {
  formatAmount,
  formatInterval,
  formatNumber,
  formatPercent,
} from './format.js';
import { layoutOf } from './gauge.js';

// Two ticks closer than this (as a share of the track) share one label.
const CLOSE_TICKS = 24;
// A label is kept this far (as a share of the track) from either end, so a tick near
// an end does not push its text out of the gauge.
const LABEL_EDGE = 7;

/**
 * One nutrient of the day on a gauge: the amount as a bar, what is wanted as a zone,
 * the range the amount can be in as a line, and the verdict as the colour. The
 * figures are the server's; this only draws them.
 *
 * `ratio` is for a ratio, which has no unit.
 */
export function Gauge({
  name,
  unit,
  amount,
  low,
  high,
  needLow,
  needHigh,
  eaten = null,
  status,
  certain,
  coverage,
  ends,
  labels,
  languageCode,
  ratio = false,
}) {
  const layout = layoutOf({ amount, low, high, needLow, needHigh, eaten });
  const show = (value) =>
    ratio
      ? formatNumber(value, languageCode)
      : formatAmount(value, unit, languageCode);
  const percent =
    layout.share === null ? null : formatPercent(layout.share, languageCode);
  const shown = coverage === undefined ? 100 : Math.round(Number(coverage));
  const verdict = `${labels[status]}${certain ? '' : ' ?'}`;
  const eatenText =
    layout.eatenFill === null ? null : `${labels.ofWhichEaten} ${show(eaten)}`;
  const range = ratio
    ? formatInterval(low, high, '', languageCode)
    : formatInterval(low, high, unit, languageCode);

  // The labels of the ticks: one each, or one for both when they are close. With one
  // tick, it is the lowest wanted or the highest allowed; with two, the lowest and
  // then the highest.
  const [first, second] = layout.ticks;
  const sign = (index) =>
    layout.ticks.length === 2
      ? ['≥', '≤'][index]
      : needLow !== null
        ? '≥'
        : '≤';
  const closeTogether =
    second !== undefined && second.at - first.at < CLOSE_TICKS;
  const tickLabels = closeTogether
    ? [
        {
          at: (first.at + second.at) / 2,
          text: `${show(first.value)} – ${show(second.value)}`,
        },
      ]
    : layout.ticks.map((tick, index) => ({
        at: tick.at,
        text: `${sign(index)} ${show(tick.value)}`,
      }));

  return (
    <div className="gauge-row">
      <div className="gauge-name">
        {name}
        {shown < 100 && (
          <small
            className="d-block text-warning-emphasis"
            title={labels.coverageNote}
          >
            {labels.coverage} {shown} %
          </small>
        )}
      </div>
      <div
        className="gauge"
        role="meter"
        aria-label={name}
        aria-valuemin={0}
        aria-valuemax={layout.max}
        aria-valuenow={Math.min(Number(amount ?? 0), layout.max)}
        aria-valuetext={`${show(amount)}${percent ? `, ${percent}` : ''}, ${verdict}${
          eatenText ? `, ${eatenText}` : ''
        }`}
        title={`${range} · ${(ends ?? []).join(' / ')}`}
      >
        <div className="gauge-track">
          <div
            className="gauge-zone"
            style={{
              left: `${layout.zone.from}%`,
              width: `${Math.max(layout.zone.to - layout.zone.from, 0.5)}%`,
            }}
          />
          <div
            className={`gauge-fill gauge-fill--${status}${
              certain ? '' : ' gauge-fill--uncertain'
            }`}
            style={{ width: `${layout.fill}%` }}
          />
          {layout.eatenFill !== null && (
            <div
              className="gauge-eaten"
              data-testid="gauge-eaten"
              style={{ width: `${layout.eatenFill}%` }}
            />
          )}
          {!layout.interval.outside && (
            <div
              className={`gauge-interval${
                layout.interval.open ? ' gauge-interval--open' : ''
              }`}
              style={{
                left: `${layout.interval.from}%`,
                width: `${Math.max(layout.interval.to - layout.interval.from, 0)}%`,
              }}
            />
          )}
          {layout.overflow && (
            <span className="gauge-overflow" aria-hidden="true">
              »
            </span>
          )}
          {layout.ticks.map((tick) => (
            <div
              key={tick.value}
              className="gauge-tick"
              style={{ left: `${tick.at}%` }}
            />
          ))}
        </div>
        {tickLabels.map((tick) => (
          <span
            key={tick.text}
            className="gauge-tick-label"
            style={{
              left: `${Math.min(Math.max(tick.at, LABEL_EDGE), 100 - LABEL_EDGE)}%`,
            }}
          >
            {tick.text}
          </span>
        ))}
      </div>
      <div className="gauge-value">
        <strong>{show(amount)}</strong>
        {percent && (
          <small
            className="d-block text-body-secondary"
            title={
              layout.against === 'low'
                ? labels.shareOfMinimum
                : labels.shareOfLimit
            }
          >
            {percent}
            {certain ? '' : ' ?'}
          </small>
        )}
        {eatenText && (
          <small className="d-block text-body-secondary">{eatenText}</small>
        )}
      </div>
    </div>
  );
}
