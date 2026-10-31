import { useEffect, useState } from 'react';

import { fill } from '../../shared/format.js';
import {
  cents,
  convertStock,
  defaultStockUnit,
  describeAmount,
  describeEquivalent,
  packageContent,
  stockUnitOptions,
  unitLabel,
} from './stockUnits.js';

/** A figure as a field holds it: no trailing zeros, empty for none. */
const asField = (value) => (value === null ? '' : String(cents(value)));

const savedQuantity = (stock) =>
  stock?.quantity == null ? null : Number(stock.quantity);

/**
 * How much of a product the user has at hand, said and changed where the product is
 * shown in full: a quantity they type, in the unit it is counted in (grams,
 * millilitres, or the pots, slices, bottles the label names, which are whole and go
 * up and down by one), kept as they leave the field (no button to save it). A button
 * adds a package, for a purchase, another says the product is used up. Left empty,
 * the stock is not counted and nothing limits what a day uses of the product. The
 * meals that are eaten take from it on their own.
 *
 * @param {object} props
 * @param {object} props.product A product of the products API, in the inventory.
 * @param {Record<string, string>} props.labels Translated by ProductListView.
 * @param {string} props.languageCode The language Django is serving.
 * @param {(product: object, quantity: number | null, unit: string) => Promise<void>} props.onCount
 *   Keeps the stock; a null quantity says it is not counted.
 */
export function StockEditor({ product, labels, languageCode, onCount }) {
  const stock = product.stock ?? null;
  const saved = savedQuantity(stock);
  const savedUnit = stock?.unit ?? defaultStockUnit(product);
  const [unit, setUnit] = useState(savedUnit);
  const [value, setValue] = useState(asField(saved));
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  // What the server holds is what the field shows: after a save, or when the meals
  // eaten have taken from it.
  useEffect(() => {
    setUnit(savedUnit);
    setValue(asField(saved));
  }, [saved, savedUnit]);

  const whole = unit === 'serving';
  const content = packageContent(product, unit);

  // The quantity the field holds, where it holds one; else the one kept.
  const shown = () => {
    const typed = Number(value);
    return value.trim() !== '' && Number.isFinite(typed) && typed >= 0
      ? typed
      : (saved ?? 0);
  };

  const save = (quantity, toUnit = unit) => {
    setBusy(true);
    setFailed(false);
    onCount(product, quantity, toUnit)
      .catch((err) => {
        console.error(err);
        setFailed(true);
        setValue(asField(saved));
        setUnit(savedUnit);
      })
      .finally(() => setBusy(false));
  };

  const revert = () => setValue(asField(saved));

  const commitQuantity = () => {
    if (value === asField(saved)) return;
    if (value.trim() === '') {
      save(null);
      return;
    }
    const quantity = Number(value);
    if (
      !Number.isFinite(quantity) ||
      quantity < 0 ||
      (whole && !Number.isInteger(quantity))
    ) {
      revert();
    } else if (quantity === saved) {
      // Written another way ("375.0"): nothing to keep.
      revert();
    } else {
      save(quantity);
    }
  };

  const chooseUnit = (toUnit) => {
    if (toUnit === unit) return;
    if (saved === null) {
      // Nothing counted yet: it is the unit the next count is in.
      setUnit(toUnit);
      return;
    }
    const quantity = convertStock(saved, unit, toUnit, product);
    if (quantity !== null) save(quantity, toUnit);
  };

  const label = unitLabel(unit, product, labels);
  const noun = product.count_noun ?? labels.stockServings;
  // The things that are counted first: it is how the product is known at home.
  const options = stockUnitOptions(product, unit, saved, labels).sort(
    (a, b) => (b.value === 'serving') - (a.value === 'serving'),
  );
  const equivalent = describeEquivalent(
    product,
    unit,
    saved,
    labels,
    languageCode,
  );
  const countedOn =
    stock?.counted_at && saved !== null
      ? new Date(stock.counted_at).toLocaleDateString(languageCode)
      : null;
  const usedUp = saved === 0;

  return (
    <div className="d-flex flex-column gap-3">
      <div className="d-flex justify-content-between align-items-baseline gap-2">
        <h3 className="h6 text-uppercase text-body-secondary fw-semibold mb-0 small">
          {labels.stock}
        </h3>
        {countedOn && (
          <span className="small text-body-secondary">
            {fill(labels.stockCountedOn, { date: countedOn })}
          </span>
        )}
      </div>

      <div className="d-flex align-items-center gap-2">
        {whole && (
          <button
            type="button"
            className="btn btn-outline-secondary stock-step"
            aria-label={fill(labels.stockRemoveOne, { noun })}
            disabled={busy || shown() <= 0}
            onClick={() => save(shown() - 1)}
          >
            <i className="fa-solid fa-minus" aria-hidden="true" />
          </button>
        )}
        <input
          type="number"
          min="0"
          step={whole ? '1' : 'any'}
          inputMode={whole ? 'numeric' : 'decimal'}
          className="form-control form-control-lg text-center fw-semibold"
          style={{ width: whole ? '5rem' : '8rem' }}
          aria-label={`${labels.stock} – ${product.name}`}
          placeholder={labels.stockNotCounted}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onBlur={commitQuantity}
          onKeyDown={(event) => {
            if (event.key === 'Enter') event.currentTarget.blur();
          }}
        />
        {whole && (
          <button
            type="button"
            className="btn btn-outline-secondary stock-step"
            aria-label={fill(labels.stockAddOne, { noun })}
            disabled={busy}
            onClick={() => save(shown() + 1)}
          >
            <i className="fa-solid fa-plus" aria-hidden="true" />
          </button>
        )}
        <span>{label}</span>
      </div>

      <p className="small text-body-secondary mb-0">
        {saved === null ? labels.stockNotCountedHint : equivalent}
      </p>

      {options.length > 1 && (
        <div className="d-flex flex-wrap align-items-center gap-2">
          <span className="small text-body-secondary">
            {labels.stockCountIn}
          </span>
          <div
            className="btn-group btn-group-sm"
            role="group"
            aria-label={labels.stockUnit}
          >
            {options.map((option) => (
              <button
                key={option.value}
                type="button"
                className={`btn ${
                  option.value === unit
                    ? 'btn-secondary'
                    : 'btn-outline-secondary'
                }`}
                aria-pressed={option.value === unit}
                disabled={busy}
                onClick={() => chooseUnit(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="d-flex flex-wrap gap-2">
        {content !== null && (
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy}
            onClick={() => save(cents(shown() + content))}
          >
            <i className="fa-solid fa-plus me-2" aria-hidden="true" />
            {fill(labels.stockOnePackage, {
              package: describeAmount(
                product,
                unit,
                content,
                labels,
                languageCode,
              ),
            })}
          </button>
        )}
        <button
          type="button"
          className="btn btn-outline-secondary"
          disabled={busy || usedUp}
          onClick={() => save(0)}
        >
          {labels.stockMarkUsedUp}
        </button>
      </div>

      <p className="small text-body-secondary d-flex gap-2 mb-0">
        <i className="fa-solid fa-circle-info mt-1" aria-hidden="true" />
        <span>{labels.stockEatenNote}</span>
      </p>

      {failed && (
        <p className="small text-danger mb-0" role="alert">
          {labels.stockSaveError}
        </p>
      )}
    </div>
  );
}
