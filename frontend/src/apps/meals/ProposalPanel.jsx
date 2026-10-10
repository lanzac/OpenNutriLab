import { DayPreview } from './DayPreview.jsx';

/** The label that says why products were left out, by the reason the server gives. */
const skippedLabel = (reason, labels) =>
  labels[`skipped_${reason}`] ?? labels.skipped;

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
  // Told apart by reason: a product with no energy value, and one that is used up.
  const reasons = [...new Set(skipped.map((product) => product.reason))];
  // The best day can be to add nothing, where meals eaten bring what the day needs.
  const message =
    status === 'optimal' && !found
      ? labels.proposal_nothing_to_add
      : labels[`proposal_${status}`];

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
        <p className="mb-2">{message}</p>
        {reasons.map((reason) => (
          <p key={reason} className="small text-body-secondary">
            {skippedLabel(reason, labels)}{' '}
            {skipped
              .filter((product) => product.reason === reason)
              .map((product) => product.name)
              .join(', ')}
          </p>
        ))}
        {found && (
          <>
            <DayPreview
              day={day}
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
