import { useEffect, useRef, useState } from 'react';

import { groupProducts } from '../products/groups.js';
import { describeServing, fill, formatAmount } from './format.js';
import { Photo } from './Photo.jsx';
import './picker.css';

// The chip that shows every group (no group has a key of null: the unclassified are '').
const ALL = null;

// Written without accents or capitals, so that "ecreme" finds "Écrémé".
const plain = (text) =>
  text
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase();

/** What a product is, in a line: its serving and what its package holds. */
function describeProduct(product, labels, languageCode) {
  return [
    product.serving && describeServing(product.serving, labels, languageCode),
    product.package &&
      formatAmount(
        product.package.quantity,
        product.package.unit,
        languageCode,
      ),
  ]
    .filter(Boolean)
    .join(' · ');
}

/** What a product is counted in when it is put in a meal: a serving if it has one. */
export const firstQuantity = (product) =>
  product.serving
    ? { quantity: 1, unit: 'serving' }
    : { quantity: 100, unit: 'g' };

/**
 * The window in which products of the inventory are chosen for a meal: with their
 * photo, filed by food group, with a search and the groups as filters. A product
 * is put in the meal by a click, with a quantity of one serving (or 100 g) that the
 * meal changes afterwards, and the window stays, so that a meal is made up in one go.
 *
 * @param {object} props
 * @param {{ kind: string, label: string, items: object[] }} props.meal
 * @param {object[]} props.inventory The products of the inventory API.
 * @param {Record<string, string>} props.labels Translated by MealsView.
 * @param {string} props.languageCode The language Django is serving.
 * @param {Record<string, string>} props.groupNames The food groups, in that language.
 * @param {string} props.placeholderImage Shown for a product with no photo.
 * @param {(kind: string, item: { barcode: string, quantity: number, unit: string }) => void} props.onAdd
 * @param {() => void} props.onClose
 */
export function ProductPicker({
  meal,
  inventory,
  labels,
  languageCode,
  groupNames,
  placeholderImage,
  onAdd,
  onClose,
}) {
  const [query, setQuery] = useState('');
  const [group, setGroup] = useState(ALL);
  const search = useRef(null);

  useEffect(() => {
    search.current?.focus();
  }, []);

  const inMeal = new Set(meal.items.map((item) => item.barcode));
  const needle = plain(query.trim());
  const groups = groupProducts(inventory, {
    names: groupNames ?? {},
    uncategorised: labels.uncategorised,
    locale: languageCode,
  });
  const shown = groups
    .filter((found) => group === ALL || found.key === group)
    .map((found) => ({
      ...found,
      products: found.subgroups
        .flatMap((sub) => sub.products)
        .filter((product) => plain(product.name).includes(needle))
        .sort((a, b) => a.name.localeCompare(b.name, languageCode)),
    }))
    .filter((found) => found.products.length > 0);

  return (
    <div
      className="picker-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="picker"
        role="dialog"
        aria-modal="true"
        aria-label={fill(labels.addToMeal, { meal: meal.label })}
        onKeyDown={(event) => {
          if (event.key === 'Escape') onClose();
        }}
      >
        <div className="picker-top">
          <div className="d-flex justify-content-between align-items-center gap-2">
            <h2 className="h5 mb-0">
              {fill(labels.addToMeal, { meal: meal.label })}
            </h2>
            <button
              type="button"
              className="btn-close"
              aria-label={labels.close}
              onClick={onClose}
            />
          </div>
          <input
            ref={search}
            type="search"
            className="form-control"
            placeholder={labels.searchPlaceholder}
            aria-label={labels.searchProduct}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          {groups.length > 1 && (
            <div
              className="picker-groups"
              role="group"
              aria-label={labels.foodGroups}
            >
              <button
                type="button"
                className={`btn btn-sm ${group === ALL ? 'btn-primary' : 'btn-outline-secondary'}`}
                aria-pressed={group === ALL}
                onClick={() => setGroup(ALL)}
              >
                {labels.allGroups}
              </button>
              {groups.map((found) => (
                <button
                  key={found.key}
                  type="button"
                  className={`btn btn-sm ${group === found.key ? 'btn-primary' : 'btn-outline-secondary'}`}
                  aria-pressed={group === found.key}
                  onClick={() => setGroup(found.key)}
                >
                  {found.name} <span className="opacity-75">{found.count}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <ul className="picker-list">
          {shown.length === 0 && (
            <li className="p-3 text-body-secondary">{labels.noProductFound}</li>
          )}
          {shown.map((found) => (
            <li key={found.key} className="list-unstyled">
              {groups.length > 1 && group === ALL && (
                <div className="picker-group-title">{found.name}</div>
              )}
              <ul className="list-unstyled m-0">
                {found.products.map((product) => {
                  const already = inMeal.has(product.barcode);
                  const usedUp =
                    product.stock?.quantity !== null &&
                    product.stock?.quantity !== undefined &&
                    Number(product.stock.quantity) === 0;
                  return (
                    <li key={product.barcode}>
                      <button
                        type="button"
                        className="picker-row"
                        disabled={already}
                        onClick={() =>
                          onAdd(meal.kind, {
                            barcode: product.barcode,
                            ...firstQuantity(product),
                          })
                        }
                      >
                        <Photo
                          src={product.image}
                          placeholderImage={placeholderImage}
                          size={48}
                        />
                        <span className="picker-row-main">
                          <span className="fw-semibold">{product.name}</span>
                          <small className="d-block text-body-secondary">
                            {describeProduct(product, labels, languageCode)}
                          </small>
                        </span>
                        <span className="picker-row-end">
                          {usedUp && (
                            <span className="badge bg-danger-subtle text-danger-emphasis border border-danger-subtle">
                              {labels.usedUp}
                            </span>
                          )}
                          {already ? (
                            <span className="small text-success-emphasis">
                              <i
                                className="fa-solid fa-check me-1"
                                aria-hidden="true"
                              />
                              {labels.inThisMeal}
                            </span>
                          ) : (
                            <i
                              className="fa-solid fa-plus text-primary"
                              aria-hidden="true"
                            />
                          )}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ul>

        <div className="picker-bottom">
          <button type="button" className="btn btn-primary" onClick={onClose}>
            {labels.closeSearch}
          </button>
        </div>
      </div>
    </div>
  );
}
