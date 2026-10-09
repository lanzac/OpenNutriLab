import './estimate.css';

import { formatNumber } from '../../../shared/format.js';
import { layoutOf } from './layout.js';

// How each verdict looks: the colour of the band and of its badge, and the label that
// says it. A row with no label to be set against has the neutral one.
const KINDS = {
  agrees: { badge: 'text-bg-success', text: 'agrees' },
  differs: { badge: 'text-bg-warning', text: null },
  used: { badge: 'text-bg-secondary', text: 'constrained' },
  none: { badge: 'text-bg-light', text: null },
};

/** The kind of verdict of a row, which colours it. */
export function kindOf({ verdict, constrained }) {
  if (constrained) return 'used';
  if (verdict === 'agrees') return 'agrees';
  if (verdict === 'declared_below' || verdict === 'declared_above')
    return 'differs';
  return 'none';
}

function verdictText(verdict, constrained, labels) {
  if (constrained) return labels.constrained;
  return (
    {
      agrees: labels.agrees,
      declared_below: labels.declaredBelow,
      declared_above: labels.declaredAbove,
      not_estimated: labels.notEstimated,
    }[verdict] ?? ''
  );
}

function verdictNote(verdict, constrained, labels) {
  if (constrained) return labels.constrainedNote;
  return (
    {
      declared_below: labels.declaredBelowNote,
      declared_above: labels.declaredAboveNote,
    }[verdict] ?? undefined
  );
}

/** A range as low to high, or "≥ low" when no upper end is known. */
export function rangeText(estimated, languageCode) {
  const low = formatNumber(estimated.low, languageCode);
  if (estimated.high === null || estimated.high === undefined)
    return `≥ ${low}`;
  return `${low} – ${formatNumber(estimated.high, languageCode)}`;
}

/**
 * One figure of the estimate on a gauge: the range it can be in as a band with its
 * point, the label's value as a tick with the rounding it is written with, and the
 * verdict of the one against the other as the colour. The figures are the server's;
 * this only draws them.
 *
 * `max` is the end of the track where rows are compared with each other (the shares of
 * a recipe), and the row's own where they are not.
 */
export function EstimateGauge({
  name,
  unit,
  // The unit after the name, where the value does not say it (a nutrient's, not a
  // share of the product's).
  unitInName = true,
  depth = 0,
  estimated,
  declared,
  verdict = null,
  constrained = false,
  confidence = null,
  coverage = null,
  max,
  labels,
  languageCode,
}) {
  const layout = layoutOf({ estimated, declared }, max);
  const kind = kindOf({ verdict, constrained });
  const text = verdictText(verdict, constrained, labels);
  const show = (value) => `${formatNumber(value, languageCode)} ${unit}`;
  const pointText = estimated ? show(estimated.point) : '–';
  const summary = [
    estimated
      ? `${labels.estimate} ${pointText} (${rangeText(estimated, languageCode)})`
      : null,
    declared ? `${labels.label} ${show(declared.amount)}` : null,
    text || null,
  ]
    .filter(Boolean)
    .join(' ; ');
  const shown = coverage === null ? 100 : Math.round(Number(coverage));

  return (
    <div className="est-row">
      <div className="est-name" style={{ '--est-depth': depth }}>
        {name}
        {unitInName && unit && (
          <span className="small text-body-secondary"> ({unit})</span>
        )}
        {text && (
          <span
            className={`badge ${KINDS[kind].badge} d-table mt-1`}
            title={verdictNote(verdict, constrained, labels)}
          >
            {text}
          </span>
        )}
      </div>
      <div className="est-gauge" role="img" aria-label={`${name} : ${summary}`}>
        <div className="est-track">
          {layout.band && (
            <>
              <div
                className={`est-band est-band--${kind}${
                  layout.band.open ? ' est-band--open' : ''
                }`}
                style={{
                  left: `${layout.band.from}%`,
                  width: `${layout.band.to - layout.band.from}%`,
                }}
                title={`${labels.estimate} : ${rangeText(estimated, languageCode)}`}
              />
              <div
                className={`est-point est-point--${kind}`}
                style={{ left: `${layout.band.point}%` }}
              />
            </>
          )}
          {layout.label?.rounding && (
            <div
              className="est-rounding"
              style={{
                left: `${layout.label.rounding.from}%`,
                width: `${layout.label.rounding.to - layout.label.rounding.from}%`,
              }}
            />
          )}
          {layout.label && (
            <div
              className="est-label-tick"
              style={{ left: `${layout.label.at}%` }}
              title={`${labels.label} : ${show(declared.amount)}`}
            />
          )}
        </div>
      </div>
      <div className="est-value">
        <strong>{pointText}</strong>
        {declared && (
          <small className="d-block text-body-secondary">
            {labels.label} {show(declared.amount)}
          </small>
        )}
        {confidence && (
          <>
            <small className="d-block text-body-secondary">
              {labels.confidence} {formatNumber(confidence.score, languageCode)}
            </small>
            <span
              className="est-confidence d-block"
              role="meter"
              aria-label={labels.confidence}
              aria-valuemin={0}
              aria-valuemax={1}
              aria-valuenow={Number(confidence.score)}
            >
              <span style={{ width: `${Number(confidence.score) * 100}%` }} />
            </span>
          </>
        )}
        {shown < 100 && (
          <small
            className="d-block text-warning-emphasis"
            title={labels.coverageNote}
          >
            {labels.coverage} {shown} %
          </small>
        )}
      </div>
    </div>
  );
}
