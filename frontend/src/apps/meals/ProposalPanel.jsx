import { DaySummary } from './DaySummary.jsx';
import { MealCard } from './MealCard.jsx';

/**
 * A day proposed from the inventory, as it would be: the meals, and the day against
 * the needs. Nothing is written until the user takes it, so the meals here only
 * read. The figures are the server's, worked out as for a day that is saved.
 */
export function ProposalPanel({
  proposal,
  labels,
  languageCode,
  needsUrl,
  busy,
  onUse,
  onClose,
}) {
  const { status, skipped, day } = proposal;
  const found = proposal.items.length > 0;

  return (
    <section
      className="card border-primary mb-4"
      aria-label={labels.proposalTitle}
    >
      <div className="card-header d-flex justify-content-between align-items-center">
        <span className="fw-semibold">{labels.proposalTitle}</span>
        <button
          type="button"
          className="btn-close"
          aria-label={labels.closeProposal}
          onClick={onClose}
        />
      </div>
      <div className="card-body">
        <p className="mb-2">{labels[`proposal_${status}`]}</p>
        {skipped.length > 0 && (
          <p className="small text-body-secondary">
            {labels.skipped} {skipped.map((product) => product.name).join(', ')}
          </p>
        )}
        {found && (
          <>
            <div className="row g-3">
              {day.meals.map((meal) => (
                <div key={meal.kind} className="col-lg-6">
                  <MealCard
                    meal={meal}
                    nutrients={day.nutrients}
                    inventory={[]}
                    labels={labels}
                    languageCode={languageCode}
                    readOnly
                  />
                </div>
              ))}
            </div>
            <DaySummary
              report={day}
              labels={labels}
              languageCode={languageCode}
              needsUrl={needsUrl}
            />
            <div className="d-flex gap-2 mt-3">
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy}
                onClick={onUse}
              >
                {labels.useDay}
              </button>
              <button
                type="button"
                className="btn btn-outline-secondary"
                onClick={onClose}
              >
                {labels.closeProposal}
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
