import { DayPreview } from './DayPreview.jsx';
import { formatNumber } from './format.js';

// "%(name)s" and the like are interpolated here: the server translated the text and
// left the figures, which it cannot know where they stand in another language.
const fill = (text, values) =>
  Object.entries(values).reduce(
    (found, [name, value]) => found.replace(`%(${name})s`, value),
    text,
  );

/** How much of what is missed a food closes, in words. */
function share(value, labels, languageCode) {
  if (Number(value) >= 1) return labels.coversNeed;
  // The browser writes the percent as the language does, with its own spaces.
  const percent = new Intl.NumberFormat(languageCode, {
    style: 'percent',
    maximumFractionDigits: 0,
  }).format(Number(value));
  return fill(labels.ofNeed, { percent });
}

function Food({ food, labels, languageCode }) {
  return (
    <li className="list-group-item">
      <div className="d-flex flex-wrap justify-content-between gap-2">
        <span className="fw-semibold">
          <a href={food.url} target="_blank" rel="noopener noreferrer">
            {food.name}
          </a>
        </span>
        <span className="text-nowrap">
          {food.meals.map((meal) => (
            <span key={meal.kind}>
              {formatNumber(meal.grams, languageCode)} g · {meal.label}
            </span>
          ))}
        </span>
      </div>
      <small className="text-body-secondary">{food.group}</small>
      <ul className="mb-0 mt-1 small">
        {food.helps.map((help) => (
          <li key={help.name + help.raised}>
            {help.raised || help.name} +
            {formatNumber(help.amount, languageCode)} {help.unit}
            {help.raised && (
              <span className="text-body-secondary">
                {' '}
                ({labels.ratio} {help.name})
              </span>
            )}
            <span className="text-body-secondary">
              {' '}
              – {share(help.share, labels, languageCode)}
            </span>
          </li>
        ))}
      </ul>
    </li>
  );
}

/**
 * Foods that would close what the inventory misses, from the CIQUAL table: how much
 * of each and in which meal, and what it closes, then the day they make. Generic
 * foods, not products: the user finds the product that is that food. Nothing here
 * is saved.
 */
export function SuggestionsPanel({
  suggestions,
  labels,
  languageCode,
  needsUrl,
  onClose,
}) {
  const { status, foods, day } = suggestions;
  const summary = fill(labels[`suggestion_${status}`] ?? '', {
    before: suggestions.missed_before,
    after: suggestions.missed_after,
    total: suggestions.total,
  });

  return (
    <section
      className="card border-info mb-4"
      aria-label={labels.suggestionsTitle}
    >
      <div className="card-header d-flex justify-content-between align-items-center">
        <span className="fw-semibold">{labels.suggestionsTitle}</span>
        <button
          type="button"
          className="btn-close"
          aria-label={labels.closeProposal}
          onClick={onClose}
        />
      </div>
      <div className="card-body">
        <p className="mb-2">{summary}</p>
        {foods.length > 0 && (
          <>
            <ul className="list-group mb-3">
              {foods.map((food) => (
                <Food
                  key={food.code}
                  food={food}
                  labels={labels}
                  languageCode={languageCode}
                />
              ))}
            </ul>
            <p className="small text-body-secondary">
              {labels.suggestionCaution}
            </p>
            <details>
              <summary className="fw-semibold">{labels.suggestedDay}</summary>
              <DayPreview
                day={day}
                labels={labels}
                languageCode={languageCode}
                needsUrl={needsUrl}
              />
            </details>
          </>
        )}
      </div>
    </section>
  );
}
