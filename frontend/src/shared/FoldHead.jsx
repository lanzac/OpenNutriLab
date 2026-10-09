import './fold.css';

/**
 * The head of a group of figures: a button that opens and closes it, with what it
 * holds said at a glance (a text and a small bar of `parts`, each a class and the
 * share of the bar it takes), so that a closed group still says how it stands.
 */
export function FoldHead({
  id,
  label,
  summary,
  parts,
  isFolded,
  onToggle,
  as: Heading = 'h3',
}) {
  return (
    <Heading className="h6 mb-0">
      <button
        type="button"
        className="group-toggle"
        aria-expanded={!isFolded}
        aria-controls={id}
        onClick={onToggle}
      >
        <i
          className={`fa-solid ${isFolded ? 'fa-chevron-right' : 'fa-chevron-down'}`}
          aria-hidden="true"
        />
        <span className="group-toggle-label">{label}</span>
        <span className="group-toggle-summary">{summary}</span>
        <span className="group-toggle-bar" aria-hidden="true">
          {parts.map((part) => (
            <span
              key={part.className}
              className={part.className}
              style={{ width: `${part.share * 100}%` }}
            />
          ))}
        </span>
      </button>
    </Heading>
  );
}
