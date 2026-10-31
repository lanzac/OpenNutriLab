import { useState } from 'react';

import { fill } from '../../shared/format.js';
import {
  describePackage,
  describeStock,
  packageAddition,
  stockStatus,
} from './stockUnits.js';

// The side of the square a photo is shown in. The stored photos are small
// (OpenFoodFacts' own sizes), so the browser scales them, none is cut.
const THUMBNAIL_SIZE = 56;

/**
 * One product of the list, said in a line: its photo, its name with what a package
 * holds under it, and where its stock stands ("3 bouteilles, in stock", "Not counted",
 * "Used up"). The whole line opens the product's sheet; the only buttons it keeps are
 * the ones that are wanted without opening it: adding a package that was just bought,
 * taking out of the inventory a product that is used up, and, among all the products,
 * putting one in the inventory.
 *
 * @param {object} props
 * @param {object} props.product A product of the products API.
 * @param {'mine' | 'all'} props.view Whether the list is the inventory or the catalogue.
 * @param {Record<string, string>} props.labels Translated by ProductListView.
 * @param {string} props.languageCode The language Django is serving.
 * @param {string} props.placeholderImage Shown for a product with no photo.
 * @param {boolean} props.selected Whether its sheet is the one open.
 * @param {(barcode: string) => void} props.onSelect
 * @param {(product: object) => void} props.onToggleInventory
 * @param {(product: object, quantity: number | null, unit: string) => Promise<void>} props.onCountStock
 */
export function ProductRow({
  product,
  view,
  labels,
  languageCode,
  placeholderImage,
  selected,
  onSelect,
  onToggleInventory,
  onCountStock,
}) {
  const [failed, setFailed] = useState(false);
  const status = stockStatus(product);
  const usedUp = status === 'used-up';
  const addition = status
    ? packageAddition(product, labels, languageCode)
    : null;
  const addLabel = addition
    ? fill(labels.stockAddPackage, { package: addition.text })
    : '';

  const addPackage = () => {
    setFailed(false);
    onCountStock(product, addition.quantity, addition.unit).catch((err) => {
      console.error(err);
      setFailed(true);
    });
  };

  // Says the line opens; it stays with the stock, where the line may wrap.
  const chevron = (
    <i
      className="fa-solid fa-chevron-right text-body-secondary small d-none d-sm-inline"
      aria-hidden="true"
    />
  );

  return (
    <li
      className={`inventory-row position-relative${selected ? ' is-selected' : ''}`}
    >
      {/* The name is beside it: the picture adds nothing to it. */}
      <img
        src={product.image || placeholderImage}
        alt=""
        width={THUMBNAIL_SIZE}
        height={THUMBNAIL_SIZE}
        className="rounded border bg-white flex-shrink-0"
        style={{ objectFit: 'contain' }}
        loading="lazy"
      />
      <div className="inventory-row-main">
        {/* Stretched over the line, so that all of it opens the sheet. */}
        <button
          type="button"
          className={`btn btn-link p-0 text-start fw-semibold text-decoration-none stretched-link ${
            usedUp ? 'text-body-secondary' : 'text-body-emphasis'
          }`}
          aria-current={selected ? 'true' : undefined}
          onClick={() => onSelect(product.barcode)}
        >
          {product.name}
        </button>
        <div className="small text-body-secondary">
          {describePackage(product, labels, languageCode)}
        </div>
      </div>

      {view === 'mine' && status && (
        <div className="inventory-row-stock">
          <div className="text-end">
            {status === 'counted' && (
              <>
                <div className="fw-semibold">
                  {describeStock(product, labels, languageCode)}
                </div>
                <div className="small text-body-secondary">
                  {labels.stockInStock}
                </div>
              </>
            )}
            {status === 'uncounted' && (
              <div className="text-body-secondary fst-italic">
                {labels.stockNotCountedRow}
              </div>
            )}
            {usedUp && (
              <span className="badge bg-danger-subtle text-danger-emphasis border border-danger-subtle fs-6 fw-semibold">
                {labels.stockUsedUp}
              </span>
            )}
          </div>
          {usedUp && (
            <button
              type="button"
              className="btn btn-sm btn-outline-secondary position-relative z-2"
              onClick={() => onToggleInventory(product)}
            >
              {labels.removeFromInventory}
            </button>
          )}
          {addition && (
            <button
              type="button"
              className="btn btn-outline-secondary position-relative z-2 inventory-row-add"
              title={addLabel}
              aria-label={`${addLabel} – ${product.name}`}
              onClick={addPackage}
            >
              <i className="fa-solid fa-plus" aria-hidden="true" />
            </button>
          )}
          {chevron}
        </div>
      )}

      {view === 'all' && (
        <div className="inventory-row-stock">
          {product.in_inventory ? (
            <span className="small text-success-emphasis">
              <i className="fa-solid fa-check me-2" aria-hidden="true" />
              {labels.inInventory}
            </span>
          ) : (
            <button
              type="button"
              className="btn btn-sm btn-outline-primary position-relative z-2"
              onClick={() => onToggleInventory(product)}
            >
              <i className="fa-solid fa-plus me-2" aria-hidden="true" />
              {labels.addToInventory}
            </button>
          )}
          {chevron}
        </div>
      )}

      {failed && (
        <small className="inventory-row-error text-danger" role="alert">
          {labels.stockSaveError}
        </small>
      )}
    </li>
  );
}
