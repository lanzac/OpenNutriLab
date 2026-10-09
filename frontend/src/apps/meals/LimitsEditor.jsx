import { useEffect, useState } from 'react';

import { fetchLimits, setLimits } from './api/client.js';
import { formatAmount } from './format.js';

/**
 * What is allowed of one product: the meals it may be in, and the most a day, or that
 * all of its package is used in the day, which only a product with a total quantity
 * can be asked.
 */
function LimitsRow({ product, meals, found, labels, csrfToken, languageCode }) {
  const kinds = meals.map((meal) => meal.kind);
  // No limits is every meal ticked and no most.
  const [chosen, setChosen] = useState(
    found && found.meals.length > 0 ? found.meals : kinds,
  );
  const [quantity, setQuantity] = useState(
    found?.max_quantity ? String(Number(found.max_quantity)) : '',
  );
  const [unit, setUnit] = useState(
    found?.max_unit || (product.serving ? 'serving' : 'g'),
  );
  const hasPackage = Boolean(product.package);
  const [useAll, setUseAll] = useState(hasPackage && Boolean(found?.use_all));
  const [status, setStatus] = useState(null);

  const toggle = (kind) => {
    setStatus(null);
    setChosen((current) =>
      current.includes(kind)
        ? current.filter((k) => k !== kind)
        : [...current, kind],
    );
  };

  const save = () => {
    // The whole package is the quantity: there is no other most.
    const most = !useAll && Number(quantity) > 0 ? Number(quantity) : null;
    setLimits(
      product.barcode,
      {
        // Every meal is any meal: it is what no limit looks like.
        meals: chosen.length === kinds.length ? [] : chosen,
        max_quantity: most,
        max_unit: most === null ? null : unit,
        use_all: useAll,
      },
      csrfToken,
    )
      .then(() => setStatus('saved'))
      .catch((err) => {
        console.error(err);
        setStatus('error');
      });
  };

  return (
    <tr>
      <td>
        {product.name}
        {product.package && (
          <small className="d-block text-body-secondary">
            {labels.totalQuantity} :{' '}
            {formatAmount(
              product.package.quantity,
              product.package.unit,
              languageCode,
            )}
          </small>
        )}
      </td>
      <td>
        {meals.map((meal) => (
          <label key={meal.kind} className="form-check form-check-inline">
            <input
              type="checkbox"
              className="form-check-input"
              checked={chosen.includes(meal.kind)}
              onChange={() => toggle(meal.kind)}
              aria-label={`${meal.label} – ${product.name}`}
            />
            <span className="form-check-label">{meal.label}</span>
          </label>
        ))}
      </td>
      <td className="text-nowrap">
        <input
          type="number"
          min="0.01"
          step="any"
          className="form-control form-control-sm d-inline-block"
          style={{ width: '5.5rem' }}
          aria-label={`${labels.limitsMost} – ${product.name}`}
          value={quantity}
          disabled={useAll}
          onChange={(event) => {
            setStatus(null);
            setQuantity(event.target.value);
          }}
        />{' '}
        <select
          className="form-select form-select-sm d-inline-block"
          style={{ width: 'auto' }}
          aria-label={`${labels.unit} – ${product.name}`}
          value={unit}
          disabled={useAll}
          onChange={(event) => {
            setStatus(null);
            setUnit(event.target.value);
          }}
        >
          {product.serving && <option value="serving">{labels.serving}</option>}
          <option value="g">g</option>
        </select>
        <label
          className="form-check d-block mt-1 mb-0"
          title={
            hasPackage ? labels.limitsWholeHelp : labels.limitsWholeNeedsPackage
          }
        >
          <input
            type="checkbox"
            className="form-check-input"
            checked={useAll}
            disabled={!hasPackage}
            onChange={() => {
              setStatus(null);
              setUseAll((current) => !current);
            }}
            aria-label={`${labels.limitsWhole} – ${product.name}`}
          />
          <span className="form-check-label small">{labels.limitsWhole}</span>
        </label>
      </td>
      <td className="text-nowrap">
        <button
          type="button"
          className="btn btn-sm btn-outline-primary"
          disabled={chosen.length === 0}
          aria-label={`${labels.save} – ${product.name}`}
          onClick={save}
        >
          {labels.save}
        </button>{' '}
        {status === 'saved' && (
          <span className="text-success small" role="status">
            {labels.saved}
          </span>
        )}
        {status === 'error' && (
          <span className="text-danger small" role="alert">
            {labels.saveError}
          </span>
        )}
      </td>
    </tr>
  );
}

/**
 * What the user allows of each product of the inventory when a day is proposed:
 * the meals it may be in, and the most of it a day. With nothing set a product may
 * be in any meal, up to a default most.
 */
export function LimitsEditor({
  meals,
  inventory,
  labels,
  csrfToken,
  languageCode,
}) {
  const [limits, setFound] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchLimits()
      .then((data) => {
        if (!cancelled)
          setFound(Object.fromEntries(data.map((l) => [l.barcode, l])));
      })
      .catch((err) => {
        console.error(err);
        if (!cancelled) setFound({});
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (inventory.length === 0) return null;

  return (
    <details className="mt-4">
      <summary className="fw-semibold">{labels.limitsTitle}</summary>
      <p className="small text-body-secondary mt-2">{labels.limitsHelp}</p>
      {limits === null ? (
        <p>{labels.loading}</p>
      ) : (
        <div className="table-responsive">
          <table className="table table-sm align-middle">
            <thead>
              <tr>
                <th>{labels.product}</th>
                <th>{labels.limitsMeals}</th>
                <th>{labels.limitsMost}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {inventory.map((product) => (
                <LimitsRow
                  key={product.barcode}
                  product={product}
                  meals={meals}
                  found={limits[product.barcode]}
                  labels={labels}
                  csrfToken={csrfToken}
                  languageCode={languageCode}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}
