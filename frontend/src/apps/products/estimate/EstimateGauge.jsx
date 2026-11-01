import './estimate.css';

import { useId, useState } from 'react';

import { fill, formatNumber } from '../../../shared/format.js';
import { factorsOf, layoutOf, placeOf, reliabilityOf } from './layout.js';

/** The kind of verdict of a row, which colours it. */
export function kindOf({ verdict, constrained }) {
  if (constrained) return 'used';
  if (verdict === 'agrees') return 'agrees';
  if (verdict === 'declared_below' || verdict === 'declared_above')
    return 'differs';
  return 'none';
}

/**
 * What a row says of its label, in words: the kind (which colours the range and the
 * words), the icon, the text, and what it means, for the detail. A figure the estimate
 * was worked out with is a starting point and not a check, whatever else is true of it.
 */
function verdictOf({ verdict, constrained, tolerated, estimated }, labels) {
  const kind = kindOf({ verdict, constrained });
  if (constrained) {
    return {
      kind,
      icon: 'fa-bullseye',
      text: labels.constrained,
      note: labels.constrainedNote,
    };
  }
  if (verdict === 'agrees') {
    return tolerated
      ? {
          kind,
          icon: 'fa-check',
          text: labels.tolerated,
          note: labels.toleratedNote,
        }
      : { kind, icon: 'fa-check', text: labels.agrees };
  }
  if (verdict === 'declared_below') {
    return {
      kind,
      icon: 'fa-caret-down',
      text: labels.declaredBelow,
      note: labels.declaredBelowNote,
    };
  }
  if (verdict === 'declared_above') {
    return {
      kind,
      icon: 'fa-caret-up',
      text: labels.declaredAbove,
      note: labels.declaredAboveNote,
    };
  }
  if (verdict === 'not_estimated') {
    return { kind, icon: 'fa-minus', text: labels.notEstimated };
  }
  return {
    kind,
    icon: 'fa-minus',
    text: estimated ? labels.estimateOnly : '',
  };
}

/** A range as low to high, or "≥ low" when no upper end is known. */
export function rangeText(estimated, languageCode) {
  const low = formatNumber(estimated.low, languageCode);
  if (estimated.high === null || estimated.high === undefined)
    return `≥ ${low}`;
  return `${low} – ${formatNumber(estimated.high, languageCode)}`;
}

/** Where a text over or under the track is set: on the mark, or leaning on an end. */
function placed(at) {
  const place = placeOf(at);
  if (place === 'start') return { left: 0 };
  if (place === 'end') return { right: 0 };
  return { left: `${at}%`, transform: 'translateX(-50%)' };
}

const WORDS = ['reliabilityLow', 'reliabilityMedium', 'reliabilityGood'];
const FACTORS = {
  coverage: ['coverage', 'coverageNote'],
  quality: ['factorQuality', 'qualityNote'],
  recipe: ['factorRecipe', 'recipeNote'],
  agreement: ['factorAgreement', 'agreementNote'],
};

/**
 * One figure of the estimate on a gauge, said in words and drawn: the range it can be
 * in as a band, the label's value as a diamond, each with its figures written beside
 * it, the verdict of the one against the other as a phrase (and as the colour of the
 * band), and how far to trust it as three dots. A row that has a detail opens to the
 * label's rounding and tolerance and the parts of the confidence. The figures are the
 * server's; this only draws them.
 *
 * `max` is the end of the track where rows are compared with each other (the shares of
 * a recipe), and the row's own where they are not. `detailed` is for the nutrients,
 * which say what the label makes of them; the ingredients are a name and a range, and
 * there can be dozens of them: their row is compact, as high as two lines of text, with
 * the label's figure under the name and the range under the estimate, not on the drawing.
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
  tolerated = false,
  confidence = null,
  detailed = false,
  max,
  labels,
  languageCode,
}) {
  const [open, setOpen] = useState(false);
  const detailId = useId();
  const layout = layoutOf({ estimated, declared }, max);
  const said = verdictOf(
    { verdict, constrained, tolerated, estimated },
    labels,
  );
  const level = reliabilityOf(confidence);
  const factors = factorsOf(confidence);
  const tail = unitInName ? '' : ` ${unit}`;
  const show = (value) => `${formatNumber(value, languageCode)} ${unit}`;
  const twoDecimals = (value) =>
    new Intl.NumberFormat(languageCode, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(Number(value));
  const pointText = estimated ? `≈ ${show(estimated.point)}` : '–';
  const summary = [
    estimated
      ? `${labels.estimate} ${show(estimated.point)} (${rangeText(estimated, languageCode)})`
      : null,
    declared ? `${labels.label} ${show(declared.amount)}` : null,
    said.text || null,
  ]
    .filter(Boolean)
    .join(' ; ');

  const caption = (() => {
    if (!layout.band) return null;
    if (layout.band.open) {
      return fill(labels.rangeOpen, {
        low: formatNumber(estimated.low, languageCode) + tail,
      });
    }
    return (
      `${formatNumber(estimated.low, languageCode)} – ` +
      `${formatNumber(estimated.high, languageCode)}${tail}`
    );
  })();
  const captionAt = layout.band
    ? layout.band.open
      ? layout.band.from
      : (layout.band.from + layout.band.to) / 2
    : null;
  const hasDetail = detailed && Boolean(estimated || declared || confidence);
  const compact = !detailed;

  return (
    <div className="est-item">
      <div className={`est-row${compact ? ' est-row--compact' : ''}`}>
        <div className="est-name" style={{ '--est-depth': depth }}>
          {name}
          {unitInName && unit && (
            <span className="small text-body-secondary"> {unit}</span>
          )}
          {compact && layout.label && (
            <div className="est-sub est-text--label">
              {fill(labels.labelAt, {
                value: formatNumber(declared.amount, languageCode) + tail,
              })}
            </div>
          )}
        </div>
        {detailed && said.text && (
          <div className={`est-verdict est-verdict--${said.kind}`}>
            <i className={`fa-solid ${said.icon}`} aria-hidden="true" />
            {said.text}
          </div>
        )}
        <div
          className="est-gauge"
          role="img"
          aria-label={`${name} : ${summary}`}
        >
          {!compact && layout.label && (
            <div
              className="est-text est-text--label"
              style={placed(layout.label.at)}
            >
              {fill(labels.labelAt, {
                value: formatNumber(declared.amount, languageCode) + tail,
              })}
            </div>
          )}
          <div className="est-track" />
          {layout.band && (
            <div
              className={`est-band est-band--${said.kind}${
                layout.band.open ? ' est-band--open' : ''
              }`}
              style={{
                left: `${layout.band.from}%`,
                width: `${layout.band.to - layout.band.from}%`,
              }}
            />
          )}
          {layout.label && (
            <div
              className="est-diamond"
              style={{ left: `${layout.label.at}%` }}
            />
          )}
          {!compact && caption && (
            <div className="est-text est-text--range" style={placed(captionAt)}>
              {caption}
            </div>
          )}
        </div>
        <div className="est-value">
          <strong>{pointText}</strong>
          {compact && caption && (
            <div className="est-sub est-text--range">{caption}</div>
          )}
        </div>
        {detailed && level && (
          <div className="est-reliability">
            <span className="est-dots" aria-hidden="true">
              {[1, 2, 3].map((dot) => (
                <span
                  key={dot}
                  className={`est-dot${dot <= level ? ' est-dot--on' : ''}`}
                />
              ))}
            </span>
            {labels[WORDS[level - 1]]}
          </div>
        )}
        {hasDetail && (
          <button
            type="button"
            className="btn btn-sm btn-outline-secondary est-toggle"
            aria-expanded={open}
            aria-controls={detailId}
            aria-label={fill(open ? labels.detailHide : labels.detailShow, {
              name,
            })}
            onClick={() => setOpen((was) => !was)}
          >
            <i
              className={`fa-solid fa-chevron-${open ? 'up' : 'down'}`}
              aria-hidden="true"
            />
          </button>
        )}
      </div>
      {hasDetail && open && (
        <div className="est-detail" id={detailId}>
          {declared && (
            <div className="est-detail-part">
              <h4>{labels.label}</h4>
              <p className="est-detail-figure">{show(declared.amount)}</p>
              {Number(declared.low) !== Number(declared.high) && (
                <p>
                  {fill(labels.detailRounding, {
                    low: show(declared.low),
                    high: show(declared.high),
                  })}
                </p>
              )}
              <p>
                {declared.tolerance_low === null ||
                declared.tolerance_low === undefined
                  ? labels.detailNoTolerance
                  : fill(labels.detailTolerance, {
                      low: show(declared.tolerance_low),
                      high: show(declared.tolerance_high),
                    })}
              </p>
            </div>
          )}
          {estimated && (
            <div className="est-detail-part">
              <h4>{labels.estimate}</h4>
              <p className="est-detail-figure">
                {rangeText(estimated, languageCode)} {unit}{' '}
                <small className="fw-normal text-body-secondary">
                  {fill(labels.bestGuess, { point: show(estimated.point) })}
                </small>
              </p>
              <p>{said.note ?? labels.rangeNote}</p>
            </div>
          )}
          {confidence && (
            <div className="est-detail-part">
              <h4>
                {labels.reliability} {twoDecimals(confidence.score)}
              </h4>
              <p>{labels.reliabilityIntro}</p>
              <ul className="est-factors">
                {factors.map((factor) => {
                  const [nameKey, noteKey] = FACTORS[factor.key];
                  const known = factor.value !== null;
                  return (
                    <li
                      key={factor.key}
                      className={factor.limiting ? 'est-factor--limiting' : ''}
                    >
                      <div className="est-factor-head">
                        <span>
                          {labels[nameKey]}
                          {factor.limiting && ` · ${labels.limiting}`}
                        </span>
                        <span>{known ? twoDecimals(factor.value) : '–'}</span>
                      </div>
                      <div className="est-factor-bar" aria-hidden="true">
                        <span
                          style={{
                            width: `${known ? factor.value * 100 : 0}%`,
                          }}
                        />
                      </div>
                      <small className="d-block text-body-secondary">
                        {labels[noteKey]}
                      </small>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
