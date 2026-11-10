import { useId, useRef, useState } from 'react';

import {
  describeServing,
  fill,
  formatAmount,
  formatInterval,
  formatPercent,
  formatServings,
  quantityStep,
} from './format.js';
import { Photo } from './Photo.jsx';
import { ProductPicker } from './ProductPicker.jsx';

// What a meal shows of what it brings, when its nutrition is opened: the rest is in
// the day's table.
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
 * that have a quantity. A volume weighs what the product's density says when it is
 * known, and counts as the same number of grams when it is not.
 */
function PackageShare({ item, labels, languageCode }) {
  if (!item.package || item.grams === null) return null;
  // What the package weighs, which is its quantity unless it is in ml of a product
  // whose density is known.
  const whole = Number(item.package_grams ?? item.package.quantity);
  const share = Number(item.grams) / whole;
  return (
    <small className="d-block text-body-secondary">
      {fill(labels.packageShare, {
        percent: formatPercent(share, languageCode),
        package: packageText(item.package, languageCode),
      })}
    </small>
  );
}

/**
 * What a unit of a product is called: its serving, as its label names it, with the
 * mass it stands for.
 */
function unitOptions(serving, labels, languageCode) {
  const options = [{ value: 'g', label: 'g' }];
  if (serving) {
    options.unshift({
      value: 'serving',
      label: describeServing(serving, labels, languageCode),
    });
  }
  return options;
}

/** How much of a product an item is, in a few words: "1 tranche · 35.7 g", "100 g". */
function quantityPhrase(item, labels, languageCode) {
  if (item.unit !== 'serving') {
    return formatAmount(item.quantity, 'g', languageCode);
  }
  const servings = formatServings(item.quantity, item.serving, labels);
  return item.grams === null
    ? servings
    : `${servings} · ${formatAmount(item.grams, 'g', languageCode)}`;
}

/** The fields that change an item: how much, in which unit, and taking it out. */
function ItemEditor({ item, labels, languageCode, onChange, onRemove, id }) {
  const [quantity, setQuantity] = useState(String(Number(item.quantity)));
  const options = unitOptions(item.serving, labels, languageCode);

  const commit = (next) => {
    const number = Number(next.quantity);
    if (number > 0) onChange(item.id, { quantity: number, unit: next.unit });
  };

  return (
    <div id={id} className="mt-2 ps-5">
      <div className="d-flex flex-wrap align-items-center gap-2">
        {/* The arrows count from `min` by `step`: from a `min` of 0.01 they landed on 1.01, 2.01... */}
        <input
          type="number"
          min="0"
          step={quantityStep(item.unit)}
          className="form-control form-control-sm"
          style={{ width: '6rem' }}
          aria-label={`${labels.quantity} – ${item.name}`}
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
          onBlur={() => {
            if (!(Number(quantity) > 0)) {
              // Nothing to keep: the field goes back to what is saved.
              setQuantity(String(Number(item.quantity)));
            } else if (Number(quantity) !== Number(item.quantity)) {
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
        <button
          type="button"
          className="btn btn-sm btn-outline-danger ms-auto"
          aria-label={`${labels.remove} – ${item.name}`}
          onClick={() => onRemove(item.id)}
        >
          <i className="fa-regular fa-trash-can" aria-hidden="true" />{' '}
          {labels.remove}
        </button>
      </div>
      {item.grams === null && (
        <small className="d-block text-body-secondary">{labels.noMass}</small>
      )}
      <PackageShare item={item} labels={labels} languageCode={languageCode} />
    </div>
  );
}

/**
 * One item of a meal, said in a line: its photo, its name and how much. The line
 * opens the fields that change it, so that a meal reads as a list and is not a form.
 */
function ItemRow({
  item,
  labels,
  languageCode,
  placeholderImage,
  onChange,
  onRemove,
}) {
  const [open, setOpen] = useState(false);
  const panel = useId();

  return (
    <li className="list-group-item">
      <button
        type="button"
        className="meal-item-head"
        aria-expanded={open}
        aria-controls={panel}
        title={labels.editQuantity}
        onClick={() => setOpen(!open)}
      >
        <Photo src={item.image} placeholderImage={placeholderImage} />
        <span className="meal-item-name">
          <span className="d-block">{item.name}</span>
          <small className="d-block text-body-secondary">
            {quantityPhrase(item, labels, languageCode)}
          </small>
        </span>
        <i
          className={`fa-solid ${open ? 'fa-chevron-up' : 'fa-chevron-down'} small text-body-secondary`}
          aria-hidden="true"
        />
      </button>
      {open && (
        // Remounted when the item changes, so that the field shows what is saved.
        <ItemEditor
          key={`${item.quantity}-${item.unit}`}
          id={panel}
          item={item}
          labels={labels}
          languageCode={languageCode}
          onChange={onChange}
          onRemove={onRemove}
        />
      )}
    </li>
  );
}

/** An item as a proposed day shows it: what and how much, with nothing to change. */
function ReadOnlyRow({ item, labels, languageCode, placeholderImage }) {
  return (
    <li className="list-group-item">
      <div className="d-flex align-items-center gap-3">
        <Photo src={item.image} placeholderImage={placeholderImage} />
        <span className="meal-item-name">
          <span className="d-block">
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
          </span>
          <small className="d-block text-body-secondary">
            {quantityPhrase(item, labels, languageCode)}
          </small>
          <PackageShare
            item={item}
            labels={labels}
            languageCode={languageCode}
          />
        </span>
      </div>
    </li>
  );
}

/**
 * Where a product is added to the meal: a button that opens the window in which the
 * inventory is looked through (see ProductPicker).
 */
function AddRow({
  meal,
  inventory,
  labels,
  languageCode,
  groupNames,
  placeholderImage,
  onAdd,
}) {
  const [picking, setPicking] = useState(false);
  const opener = useRef(null);

  if (inventory.length === 0) return null;

  return (
    <li className="list-group-item">
      <button
        ref={opener}
        type="button"
        className="btn btn-sm btn-outline-primary"
        aria-label={`${labels.addProduct} – ${meal.label}`}
        aria-haspopup="dialog"
        onClick={() => setPicking(true)}
      >
        <i className="fa-solid fa-plus" aria-hidden="true" />{' '}
        {labels.addProduct}
      </button>
      {picking && (
        <ProductPicker
          meal={meal}
          inventory={inventory}
          labels={labels}
          languageCode={languageCode}
          groupNames={groupNames}
          placeholderImage={placeholderImage}
          onAdd={onAdd}
          onClose={() => {
            setPicking(false);
            // The page is where it was.
            opener.current?.focus();
          }}
        />
      )}
    </li>
  );
}

/**
 * Whether the meal is behind the user. Editable, a button that says what it does and,
 * pressed, that it is done; in a day that is only shown, a badge: "Eaten" for a meal
 * that is, "To add" for what is there to be eaten.
 */
function EatenMark({ meal, labels, readOnly, onEat }) {
  if (readOnly) {
    if (meal.eaten) {
      return <span className="badge text-bg-success">{labels.eaten}</span>;
    }
    return meal.items.length > 0 ? (
      <span className="badge text-bg-primary">{labels.toAdd}</span>
    ) : null;
  }
  return (
    <button
      type="button"
      className={`btn btn-sm ${meal.eaten ? 'btn-success' : 'btn-outline-secondary'}`}
      aria-pressed={meal.eaten}
      aria-label={`${meal.eaten ? labels.eaten : labels.markEaten} – ${meal.label}`}
      title={meal.eaten ? labels.eatenTitle : labels.markEatenTitle}
      onClick={() => onEat(meal.kind, !meal.eaten)}
    >
      <i
        className={`${meal.eaten ? 'fa-solid' : 'fa-regular'} fa-circle-check`}
        aria-hidden="true"
      />{' '}
      {meal.eaten ? labels.eaten : labels.markEaten}
    </button>
  );
}

/** The figures a meal brings, opened from a line under it. */
function MealDetails({
  meal,
  nutrients,
  labels,
  languageCode,
  open,
  onToggle,
}) {
  const shown = SHOWN.filter((code) => meal.totals[code]);
  const id = useId();
  if (shown.length === 0) return null;
  return (
    <div className="card-footer small">
      <button
        type="button"
        className="btn btn-link btn-sm p-0 text-decoration-none"
        aria-expanded={open}
        aria-controls={id}
        onClick={onToggle}
      >
        <i
          className={`fa-solid ${open ? 'fa-chevron-down' : 'fa-chevron-right'} me-1`}
          aria-hidden="true"
        />
        {labels.mealDetails}
      </button>
      {open && (
        <dl id={id} className="row mb-0 mt-2">
          {shown.map((code) => {
            const total = meal.totals[code];
            const { name, unit } = nutrients[code];
            return (
              <div key={code} className="col-6 d-flex justify-content-between">
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
      )}
    </div>
  );
}

/**
 * A meal: its name, what it brings in energy, whether it is eaten, its items as a
 * list that opens where one is to be changed, and the nutrition behind a line.
 *
 * `fold` says whether the nutrition is open and how to toggle it, when the page keeps
 * that from one visit to the next; without it the card keeps it for itself.
 */
export function MealCard({
  meal,
  nutrients,
  inventory,
  labels,
  languageCode,
  groupNames,
  placeholderImage,
  fold,
  onAdd,
  onChange,
  onRemove,
  onEat,
  readOnly = false,
}) {
  const [ownOpen, setOwnOpen] = useState(false);
  const detailsOpen = fold ? fold.open : ownOpen;
  const toggleDetails = fold ? fold.toggle : () => setOwnOpen(!ownOpen);
  const energy = meal.totals.energy;

  return (
    <section
      className={`card${meal.eaten ? ' border-success' : ''}`}
      aria-label={meal.label}
    >
      <div
        className={`card-header d-flex justify-content-between align-items-center gap-2${
          meal.eaten ? ' bg-success-subtle' : ''
        }`}
      >
        <span>
          <span className="fw-semibold">{meal.label}</span>
          {energy && meal.items.length > 0 && (
            <span className="ms-2 text-body-secondary">
              {formatAmount(energy.amount, nutrients.energy.unit, languageCode)}
            </span>
          )}
        </span>
        <EatenMark
          meal={meal}
          labels={labels}
          readOnly={readOnly}
          onEat={onEat}
        />
      </div>
      <ul className="list-group list-group-flush">
        {meal.items.length === 0 && (
          <li className="list-group-item text-body-secondary">
            {meal.eaten ? labels.emptyMealEaten : labels.emptyMeal}
          </li>
        )}
        {meal.items.map((item) =>
          readOnly ? (
            <ReadOnlyRow
              key={item.barcode}
              item={item}
              labels={labels}
              languageCode={languageCode}
              placeholderImage={placeholderImage}
            />
          ) : (
            <ItemRow
              key={item.id}
              item={item}
              labels={labels}
              languageCode={languageCode}
              placeholderImage={placeholderImage}
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
            groupNames={groupNames}
            placeholderImage={placeholderImage}
            onAdd={onAdd}
          />
        )}
      </ul>
      <MealDetails
        meal={meal}
        nutrients={nutrients}
        labels={labels}
        languageCode={languageCode}
        open={detailsOpen}
        onToggle={toggleDetails}
      />
    </section>
  );
}
