import { useState } from 'react';

import { fill, formatAmount, formatInterval, formatPercent } from './format.js';

// What a meal shows of what it brings: the rest is in the day's table.
const SHOWN = [
  'energy',
  'proteins',
  'fat',
  'carbohydrates',
  'fiber',
  'omega_3',
  'omega_6',
];

/** What a product's package holds, "500 g". */
const packageText = (pack, languageCode) =>
  formatAmount(pack.quantity, pack.unit, languageCode);

/**
 * How much of a package an item is, "14 % of a package of 500 g", for the products
 * that have a quantity. A volume counts as the same number of grams.
 */
function PackageShare({ item, labels, languageCode }) {
  if (!item.package || item.grams === null) return null;
  const share = Number(item.grams) / Number(item.package.quantity);
  return (
    <small className="d-block text-body-secondary">
      {fill(labels.packageShare, {
        percent: formatPercent(share, languageCode),
        package: packageText(item.package, languageCode),
      })}
    </small>
  );
}

/** What a unit of a product is called: its serving, with the mass it stands for. */
function unitOptions(serving, labels, languageCode) {
  const options = [{ value: 'g', label: 'g' }];
  if (serving) {
    const mass = `${new Intl.NumberFormat(languageCode).format(Number(serving.quantity))} ${serving.unit}`;
    options.unshift({
      value: 'serving',
      label: `${labels.serving} (${mass})`,
    });
  }
  return options;
}

function ItemRow({ item, labels, languageCode, onChange, onRemove }) {
  const [quantity, setQuantity] = useState(String(Number(item.quantity)));
  const options = unitOptions(item.serving, labels, languageCode);

  const commit = (next) => {
    const number = Number(next.quantity);
    if (number > 0) onChange(item.id, { quantity: number, unit: next.unit });
  };

  return (
    <li className="list-group-item">
      <div className="d-flex justify-content-between align-items-start gap-2">
        <span>{item.name}</span>
        <button
          type="button"
          className="btn btn-sm btn-outline-danger"
          aria-label={`${labels.remove} – ${item.name}`}
          onClick={() => onRemove(item.id)}
        >
          <i className="fa-regular fa-trash-can" />
        </button>
      </div>
      <div className="d-flex flex-wrap align-items-center gap-2 mt-1">
        <input
          type="number"
          min="0.01"
          step="any"
          className="form-control form-control-sm"
          style={{ width: '6rem' }}
          aria-label={`${labels.quantity} – ${item.name}`}
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
          onBlur={() => {
            if (Number(quantity) !== Number(item.quantity)) {
              commit({ quantity, unit: item.unit });
            }
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') event.currentTarget.blur();
          }}
        />
        <select
          className="form-select form-select-sm"
          style={{ width: 'auto' }}
          aria-label={`${labels.unit} – ${item.name}`}
          value={item.unit}
          onChange={(event) => commit({ quantity, unit: event.target.value })}
        >
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <small className="text-body-secondary">
          {item.grams === null
            ? labels.noMass
            : formatAmount(item.grams, 'g', languageCode)}
        </small>
      </div>
      <PackageShare item={item} labels={labels} languageCode={languageCode} />
    </li>
  );
}

/** An item as a proposed day shows it: what and how much, with nothing to change. */
function ReadOnlyRow({ item, labels, languageCode }) {
  const serving =
    item.unit === 'serving'
      ? `${Number(item.quantity)} ${labels.serving}`
      : `${Number(item.quantity)} g`;
  return (
    <li className="list-group-item d-flex justify-content-between gap-2">
      <span>
        {item.name}
        {item.generic && (
          <>
            {' '}
            <a
              className="badge text-bg-info text-decoration-none"
              href={item.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {labels.suggestedFood}
            </a>
          </>
        )}
        <PackageShare item={item} labels={labels} languageCode={languageCode} />
      </span>
      <span className="text-nowrap text-body-secondary">
        {serving}
        {item.unit === 'serving' && item.grams !== null && (
          <> ({formatAmount(item.grams, 'g', languageCode)})</>
        )}
      </span>
    </li>
  );
}

function AddRow({ meal, inventory, labels, languageCode, onAdd }) {
  const [barcode, setBarcode] = useState('');
  const [quantity, setQuantity] = useState('1');
  const [unit, setUnit] = useState('serving');

  const inMeal = new Set(meal.items.map((item) => item.barcode));
  const available = inventory.filter((product) => !inMeal.has(product.barcode));
  const chosen = available.find((product) => product.barcode === barcode);
  const options = unitOptions(chosen?.serving, labels, languageCode);

  const choose = (value) => {
    const product = available.find((p) => p.barcode === value);
    setBarcode(value);
    // A product with a serving is counted in servings, the others in grams.
    setUnit(product?.serving ? 'serving' : 'g');
    setQuantity(product?.serving ? '1' : '100');
  };

  if (available.length === 0) return null;

  return (
    <li className="list-group-item">
      <select
        className="form-select form-select-sm"
        aria-label={`${labels.addProduct} – ${meal.label}`}
        value={barcode}
        onChange={(event) => choose(event.target.value)}
      >
        <option value="">{labels.chooseProduct}</option>
        {available.map((product) => (
          <option key={product.barcode} value={product.barcode}>
            {product.package
              ? `${product.name} (${packageText(product.package, languageCode)})`
              : product.name}
          </option>
        ))}
      </select>
      {chosen && (
        <div className="d-flex flex-wrap align-items-center gap-2 mt-2">
          <input
            type="number"
            min="0.01"
            step="any"
            className="form-control form-control-sm"
            style={{ width: '6rem' }}
            aria-label={`${labels.quantity} – ${meal.label}`}
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
          />
          <select
            className="form-select form-select-sm"
            style={{ width: 'auto' }}
            aria-label={`${labels.unit} – ${meal.label}`}
            value={unit}
            onChange={(event) => setUnit(event.target.value)}
          >
            {options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            disabled={!(Number(quantity) > 0)}
            onClick={() => {
              onAdd(meal.kind, { barcode, quantity: Number(quantity), unit });
              setBarcode('');
            }}
          >
            {labels.add}
          </button>
        </div>
      )}
    </li>
  );
}

export function MealCard({
  meal,
  nutrients,
  inventory,
  labels,
  languageCode,
  onAdd,
  onChange,
  onRemove,
  readOnly = false,
}) {
  const shown = SHOWN.filter((code) => meal.totals[code]);

  return (
    <section className="card h-100" aria-label={meal.label}>
      <div className="card-header fw-semibold">{meal.label}</div>
      <ul className="list-group list-group-flush">
        {meal.items.length === 0 && (
          <li className="list-group-item text-body-secondary">
            {labels.emptyMeal}
          </li>
        )}
        {meal.items.map((item) =>
          readOnly ? (
            <ReadOnlyRow
              key={item.barcode}
              item={item}
              labels={labels}
              languageCode={languageCode}
            />
          ) : (
            <ItemRow
              key={`${item.id}-${item.quantity}-${item.unit}`}
              item={item}
              labels={labels}
              languageCode={languageCode}
              onChange={onChange}
              onRemove={onRemove}
            />
          ),
        )}
        {!readOnly && (
          <AddRow
            meal={meal}
            inventory={inventory}
            labels={labels}
            languageCode={languageCode}
            onAdd={onAdd}
          />
        )}
      </ul>
      {shown.length > 0 && (
        <div className="card-footer small">
          <dl className="row mb-0">
            {shown.map((code) => {
              const total = meal.totals[code];
              const { name, unit } = nutrients[code];
              return (
                <div
                  key={code}
                  className="col-6 d-flex justify-content-between"
                >
                  <dt className="fw-normal">{name}</dt>
                  <dd
                    className="mb-0"
                    title={`${formatInterval(total.low, total.high, unit, languageCode)} · ${labels.coverage} ${Math.round(Number(total.coverage))} %`}
                  >
                    {formatAmount(total.amount, unit, languageCode)}
                  </dd>
                </div>
              );
            })}
          </dl>
        </div>
      )}
    </section>
  );
}
