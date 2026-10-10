import { useEffect, useId, useMemo, useRef, useState } from 'react';

import { groupProducts } from '../products/groups.js';
import { fetchLimits, setAllEnabled, setLimits } from './api/client.js';
import { fill, formatAmount, quantityStep, servingName } from './format.js';

// A quantity being typed is saved once it has been left alone this long, or as soon
// as the field is left.
const TYPING_PAUSE_MS = 700;

// What a product has when nothing is set of it: any meal, no most, in use.
const NO_LIMITS = {
  meals: [],
  max_quantity: null,
  max_unit: '',
  use_all: false,
  enabled: true,
};

/**
 * What is allowed of one product: whether it is used at all, the meals it may be in,
 * and the most a day, or that all of its package is used in the day, which only a
 * product with a total quantity can be asked. A change is handed to `onChange` as the
 * whole of what is allowed of the product, in the shape the server keeps it.
 */
function LimitsRow({ product, meals, found, labels, languageCode, onChange }) {
  const switchId = useId();
  const kinds = meals.map((meal) => meal.kind);
  // No limits is every meal ticked and no most.
  const chosen = found.meals.length > 0 ? found.meals : kinds;
  const [quantity, setQuantity] = useState(
    found.max_quantity ? String(Number(found.max_quantity)) : '',
  );
  const [unit, setUnit] = useState(
    found.max_unit || (product.serving ? 'serving' : 'g'),
  );
  const pause = useRef(null);
  const hasPackage = Boolean(product.package);
  const useAll = hasPackage && Boolean(found.use_all);
  const used = found.enabled;

  useEffect(() => () => clearTimeout(pause.current), []);

  // `changes` are what the user just did; the rest is as it stands.
  const send = (changes = {}) => {
    const next = {
      meals: found.meals,
      useAll,
      enabled: used,
      quantity,
      unit,
      ...changes,
    };
    // The whole package is the quantity: there is no other most.
    const most =
      !next.useAll && Number(next.quantity) > 0 ? Number(next.quantity) : null;
    onChange({
      meals: next.meals,
      max_quantity: most,
      max_unit: most === null ? null : next.unit,
      use_all: next.useAll,
      enabled: next.enabled,
    });
  };

  const toggle = (kind) => {
    const next = chosen.includes(kind)
      ? chosen.filter((k) => k !== kind)
      : [...chosen, kind];
    const ordered = kinds.filter((k) => next.includes(k));
    // Every meal is any meal: it is what no limit looks like.
    send({ meals: ordered.length === kinds.length ? [] : ordered });
  };

  const type = (value) => {
    setQuantity(value);
    clearTimeout(pause.current);
    pause.current = setTimeout(() => {
      pause.current = null;
      send({ quantity: value });
    }, TYPING_PAUSE_MS);
  };

  // Leaving the field saves what was typed without waiting for the pause.
  const leave = () => {
    if (pause.current === null) return;
    clearTimeout(pause.current);
    pause.current = null;
    send();
  };

  return (
    <tr className={used ? undefined : 'text-body-secondary'}>
      <td>
        <div className="form-check form-switch mb-0">
          <input
            id={switchId}
            type="checkbox"
            role="switch"
            className="form-check-input"
            checked={used}
            aria-label={`${labels.limitsUse} – ${product.name}`}
            onChange={() => send({ enabled: !used })}
          />
          <label htmlFor={switchId} className="form-check-label">
            {product.name}
          </label>
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
        </div>
      </td>
      <td>
        {meals.map((meal) => {
          // A product in no meal is a product left out: that is the switch's.
          const last = chosen.length === 1 && chosen.includes(meal.kind);
          return (
            <label
              key={meal.kind}
              className="form-check form-check-inline"
              title={last ? labels.limitsKeepOneMeal : undefined}
            >
              <input
                type="checkbox"
                className="form-check-input"
                checked={chosen.includes(meal.kind)}
                disabled={!used || last}
                onChange={() => toggle(meal.kind)}
                aria-label={`${meal.label} – ${product.name}`}
              />
              <span className="form-check-label">{meal.label}</span>
            </label>
          );
        })}
      </td>
      <td className="text-nowrap">
        <input
          type="number"
          min="0"
          step={quantityStep(unit)}
          className="form-control form-control-sm d-inline-block"
          style={{ width: '5.5rem' }}
          aria-label={`${labels.limitsMost} – ${product.name}`}
          value={quantity}
          disabled={!used || useAll}
          onChange={(event) => type(event.target.value)}
          onBlur={leave}
        />{' '}
        <select
          className="form-select form-select-sm d-inline-block"
          style={{ width: 'auto' }}
          aria-label={`${labels.unit} – ${product.name}`}
          value={unit}
          disabled={!used || useAll}
          onChange={(event) => {
            setUnit(event.target.value);
            send({ unit: event.target.value });
          }}
        >
          {product.serving && (
            <option value="serving">
              {servingName(product.serving, labels)}
            </option>
          )}
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
            disabled={!used || !hasPackage}
            onChange={() => send({ useAll: !useAll })}
            aria-label={`${labels.limitsWhole} – ${product.name}`}
          />
          <span className="form-check-label small">{labels.limitsWhole}</span>
        </label>
      </td>
    </tr>
  );
}

/**
 * What the user allows of each product of the inventory when a day is proposed:
 * whether it is used, the meals it may be in, and the most of it a day. With nothing
 * set a product may be in any meal, up to a default most. The products are cut into
 * the food groups they are filed under.
 *
 * Nothing is left to a button: a change is saved as it is made, and the state shown is
 * the server's again if it cannot be.
 */
export function LimitsEditor({
  meals,
  inventory,
  labels,
  csrfToken,
  languageCode,
  groupNames,
}) {
  const allId = useId();
  // By barcode; null until the server has answered.
  const [limits, setFound] = useState(null);
  // Bumped to ask the server again.
  const [reading, setReading] = useState(0);
  // 'saving' while writes are on their way, then 'saved', or 'error'.
  const [status, setStatus] = useState(null);
  const writing = useRef(0);

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
  }, [reading]);

  const groups = useMemo(() => {
    const byName = (a, b) => a.name.localeCompare(b.name, languageCode);
    return groupProducts(inventory, {
      names: groupNames ?? {},
      uncategorised: labels.uncategorised,
      locale: languageCode,
    }).map((group) => ({
      ...group,
      products: group.subgroups
        .flatMap((subgroup) => subgroup.products)
        .sort(byName),
    }));
  }, [inventory, groupNames, labels.uncategorised, languageCode]);

  // Shows the change at once and sends it; if it cannot be kept, shows what is.
  const change = (send, show) => {
    show();
    writing.current += 1;
    setStatus('saving');
    send()
      .then(() => {
        writing.current -= 1;
        if (writing.current === 0) {
          setStatus((now) => (now === 'error' ? now : 'saved'));
        }
      })
      .catch((err) => {
        console.error(err);
        writing.current -= 1;
        setStatus('error');
        if (writing.current === 0) {
          setFound(null);
          setReading((n) => n + 1);
        }
      });
  };

  if (inventory.length === 0) return null;

  const foundFor = (barcode) => limits?.[barcode] ?? NO_LIMITS;
  const inUse = inventory.filter((p) => foundFor(p.barcode).enabled).length;
  const everyUsed = inUse === inventory.length;

  const setOne = (barcode, record) =>
    change(
      () => setLimits(barcode, record, csrfToken),
      () => setFound((now) => ({ ...now, [barcode]: record })),
    );

  const setAll = () => {
    const enabled = !everyUsed;
    change(
      () => setAllEnabled(enabled, csrfToken),
      () =>
        setFound((now) =>
          Object.fromEntries(
            inventory.map((p) => [
              p.barcode,
              { ...(now[p.barcode] ?? NO_LIMITS), enabled },
            ]),
          ),
        ),
    );
  };

  return (
    <details className="mt-4">
      <summary className="fw-semibold">{labels.limitsTitle}</summary>
      <p className="small text-body-secondary mt-2">{labels.limitsHelp}</p>
      {limits === null ? (
        <p>{labels.loading}</p>
      ) : (
        <>
          <div className="d-flex flex-wrap align-items-center gap-3 mb-2">
            <div className="form-check form-switch mb-0">
              <input
                id={allId}
                type="checkbox"
                role="switch"
                className="form-check-input"
                checked={everyUsed}
                onChange={setAll}
              />
              <label htmlFor={allId} className="form-check-label fw-semibold">
                {labels.limitsUseAll}
              </label>
            </div>
            <small className="text-body-secondary">
              {fill(labels.limitsInUse, {
                used: inUse,
                total: inventory.length,
              })}
            </small>
            <span role="status" className="ms-auto small text-body-secondary">
              {status === 'saving' && labels.limitsSaving}
              {status === 'saved' && (
                <span className="text-success">{labels.saved}</span>
              )}
            </span>
          </div>
          {status === 'error' && (
            <p className="text-danger small" role="alert">
              {labels.saveError}
            </p>
          )}
          <div className="table-responsive">
            <table className="table table-sm align-middle">
              <thead>
                <tr>
                  <th>{labels.product}</th>
                  <th>{labels.limitsMeals}</th>
                  <th>{labels.limitsMost}</th>
                </tr>
              </thead>
              {groups.map((group) => (
                <tbody key={group.key || 'unclassified'}>
                  <tr>
                    <th
                      scope="colgroup"
                      colSpan={3}
                      className="bg-body-tertiary"
                    >
                      {group.name}{' '}
                      <span className="badge rounded-pill text-bg-secondary">
                        {group.count}
                      </span>
                    </th>
                  </tr>
                  {group.products.map((product) => (
                    <LimitsRow
                      key={product.barcode}
                      product={product}
                      meals={meals}
                      found={foundFor(product.barcode)}
                      labels={labels}
                      languageCode={languageCode}
                      onChange={(record) => setOne(product.barcode, record)}
                    />
                  ))}
                </tbody>
              ))}
            </table>
          </div>
        </>
      )}
    </details>
  );
}
