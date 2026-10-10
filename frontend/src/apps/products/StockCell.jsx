import { useEffect, useState } from 'react';

import { fill } from '../../shared/format.js';
import {
  cents,
  convertStock,
  packageContent,
  stockUnitOptions,
  unitLabel,
} from './stockUnits.js';

/** A hair over a whole number is that whole number. */
const EPSILON = 1e-6;

/** A figure as a field holds it: no trailing zeros, empty for none. */
const asField = (value) => (value === null ? '' : String(cents(value)));

const savedQuantity = (stock) =>
  stock?.quantity == null ? null : Number(stock.quantity);

/**
 * How much of a product the user has at hand: a quantity they type, in the unit it
 * is counted in (grams, millilitres, or the pots, slices, bottles the label names,
 * which are whole), kept as they leave the field (no button to save it). Next to it,
 * how many packages that is, which is as good to type: "2 × 135 g" is 270 g. A button
 * adds a package, for a purchase. Left empty, the stock is not counted and nothing
 * limits what a day uses of the product; at nothing, it is used up. The meals that are
 * eaten take from it on their own.
 *
 * @param {object} props
 * @param {object} props.product A product of the products API.
 * @param {Record<string, string>} props.labels Translated by ProductListView.
 * @param {string} props.languageCode The language Django is serving.
 * @param {(product: object, quantity: number | null, unit: string) => Promise<void>} props.onCount
 *   Keeps the stock; a null quantity says it is not counted.
 */
export function StockCell({ product, labels, languageCode, onCount }) {
  const stock = product.stock ?? null;
  const saved = savedQuantity(stock);
  const [unit, setUnit] = useState(stock?.unit ?? 'g');
  const [value, setValue] = useState(asField(saved));
  const [packs, setPacks] = useState('');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const content = packageContent(product, unit);
  const packsOf = (quantity) =>
    quantity === null || content === null ? '' : asField(quantity / content);

  // What the server holds is what the fields show: after a save, or when the meals
  // eaten have taken from it.
  const savedUnit = stock?.unit;
  useEffect(() => {
    setUnit(savedUnit ?? 'g');
    setValue(asField(saved));
    // Not `packsOf`: it follows the unit, which has just been set.
    setPacks(
      saved === null || packageContent(product, savedUnit) === null
        ? ''
        : asField(saved / packageContent(product, savedUnit)),
    );
  }, [saved, savedUnit, product]);

  if (!product.in_inventory || stock === null) return <td />;

  const whole = unit === 'serving';
  const label = unitLabel(unit, product, labels);

  const save = (quantity, toUnit = unit) => {
    setBusy(true);
    setFailed(false);
    onCount(product, quantity, toUnit)
      .catch((err) => {
        console.error(err);
        setFailed(true);
        setValue(asField(saved));
        setPacks(packsOf(saved));
        setUnit(savedUnit ?? 'g');
      })
      .finally(() => setBusy(false));
  };

  const revert = () => {
    setValue(asField(saved));
    setPacks(packsOf(saved));
  };

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

  // How many packages: the quantity they come to, in whole servings where it counts them.
  const commitPacks = () => {
    if (packs === packsOf(saved)) return;
    const count = Number(packs);
    if (packs.trim() === '' || !Number.isFinite(count) || count < 0) {
      revert();
      return;
    }
    const total = count * content;
    const quantity = whole ? Math.ceil(total - EPSILON) : cents(total);
    if (quantity === saved) revert();
    else save(quantity);
  };

  const chooseUnit = (toUnit) => {
    if (saved === null) {
      // Nothing counted yet: it is the unit the next count is in.
      setUnit(toUnit);
      setPacks('');
      return;
    }
    const quantity = convertStock(saved, unit, toUnit, product);
    if (quantity !== null) save(quantity, toUnit);
  };

  const options = stockUnitOptions(product, unit, saved, labels);
  const contentText =
    content === null
      ? ''
      : `${new Intl.NumberFormat(languageCode).format(content)} ${label}`;
  const addPackageLabel = fill(labels.stockAddPackage, {
    package: contentText,
  });
  const usedUp = stock.quantity !== null && Number(stock.quantity) === 0;

  return (
    <td className="text-nowrap">
      <div className="d-flex flex-wrap align-items-center gap-1">
        {content !== null && (
          <>
            <input
              type="number"
              min="0"
              step="any"
              inputMode="decimal"
              className="form-control form-control-sm"
              style={{ width: '4.5rem' }}
              aria-label={`${labels.stockPackages} – ${product.name}`}
              value={packs}
              onChange={(event) => setPacks(event.target.value)}
              onBlur={commitPacks}
              onKeyDown={(event) => {
                if (event.key === 'Enter') event.currentTarget.blur();
              }}
            />
            <span className="small text-body-secondary">× {contentText} =</span>
          </>
        )}
        <input
          type="number"
          min="0"
          step={whole ? '1' : 'any'}
          inputMode={whole ? 'numeric' : 'decimal'}
          className="form-control form-control-sm"
          style={{ width: '6rem' }}
          aria-label={`${labels.stock} – ${product.name}`}
          placeholder={labels.stockNotCounted}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onBlur={commitQuantity}
          onKeyDown={(event) => {
            if (event.key === 'Enter') event.currentTarget.blur();
          }}
        />
        {options.length > 1 ? (
          <select
            className="form-select form-select-sm"
            style={{ width: 'auto' }}
            aria-label={`${labels.stockUnit} – ${product.name}`}
            value={unit}
            disabled={busy}
            onChange={(event) => chooseUnit(event.target.value)}
          >
            {options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        ) : (
          <span className="small text-body-secondary">{label}</span>
        )}
        {content !== null && (
          <button
            type="button"
            className="btn btn-sm btn-outline-secondary"
            title={addPackageLabel}
            aria-label={`${addPackageLabel} – ${product.name}`}
            disabled={busy}
            onClick={() => save(cents((saved ?? 0) + content))}
          >
            <i className="fa-solid fa-plus" />
          </button>
        )}
        {usedUp && (
          <span className="badge text-bg-danger">{labels.stockUsedUp}</span>
        )}
      </div>
      {failed && (
        <small className="d-block text-danger" role="alert">
          {labels.stockSaveError}
        </small>
      )}
    </td>
  );
}
