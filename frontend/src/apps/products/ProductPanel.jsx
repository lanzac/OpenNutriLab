import { useEffect, useRef } from 'react';

import { Barcode } from './Barcode.jsx';
import { StockEditor } from './StockEditor.jsx';
import { describePackage } from './stockUnits.js';

// Django's edit/delete class-based views still own these URLs (see
// opennutrilab/products/urls.py) - React only needs to build links to them.
// Product.barcode is the model's primary key (see opennutrilab/products/models.py),
// matching the <str:pk> URL parameter.
const productEditUrl = (barcode) => `/products/${barcode}/edit/`;
const productDeleteUrl = (barcode) => `/products/${barcode}/delete/`;

const PHOTO_SIZE = 88;
const BARCODE_WIDTH = 180;

// Where the panel is a sheet over the whole page rather than a column (see inventory.css).
const SHEET_QUERY = '(max-width: 991.98px)';

const isSheet = () =>
  typeof window.matchMedia === 'function' &&
  window.matchMedia(SHEET_QUERY).matches;

/** The serving as the label gives it: "1 pot (100 g)", or just "100 g". */
function describeServing(serving, languageCode) {
  const size = `${new Intl.NumberFormat(languageCode).format(Number(serving.quantity))} ${serving.unit}`;
  return serving.name ? `${serving.name} (${size})` : size;
}

/**
 * A product shown in full: what it is, how much of it is at hand (and the means to
 * say so), and what can be done with it, each action under the name of what it
 * does. A column beside the list on a wide screen, a sheet over it on a phone.
 *
 * @param {object} props
 * @param {object} props.product A product of the products API.
 * @param {string} props.groupPath Where it is filed, "Boissons › Boissons sucrées".
 * @param {Record<string, string>} props.labels Translated by ProductListView.
 * @param {string} props.csrfToken For the delete form, a plain POST to Django.
 * @param {string} props.languageCode The language Django is serving.
 * @param {boolean} props.canDelete True for staff only.
 * @param {string} props.placeholderImage Shown for a product with no photo.
 * @param {() => void} props.onClose
 * @param {(product: object) => void} props.onToggleInventory
 * @param {(product: object, quantity: number | null, unit: string) => Promise<void>} props.onCountStock
 */
export function ProductPanel({
  product,
  groupPath,
  labels,
  csrfToken,
  languageCode,
  canDelete,
  placeholderImage,
  onClose,
  onToggleInventory,
  onCountStock,
}) {
  const heading = useRef(null);

  // A sheet that opens over the page starts where it is read from; a column beside
  // the list leaves the focus where it was, so the list can still be walked.
  useEffect(() => {
    if (isSheet()) heading.current?.focus();
  }, [product.barcode]);

  const packageText = describePackage(product, labels, languageCode);

  return (
    <aside
      className="inventory-panel"
      aria-label={labels.productSheet}
      onKeyDown={(event) => {
        if (event.key === 'Escape') onClose();
      }}
    >
      {/* What leads out of the sheet is at its top: the whole sheet of the product,
          and the way back (a button of its own on a phone, where the sheet is the
          page; a cross beside the list, where it is a column). */}
      <div className="inventory-panel-top">
        <button
          type="button"
          className="btn btn-link px-0 d-lg-none"
          onClick={onClose}
        >
          <i className="fa-solid fa-chevron-left me-2" aria-hidden="true" />
          {labels.inventory}
        </button>
        <a
          className="btn btn-primary inventory-panel-open"
          href={productEditUrl(product.barcode)}
        >
          {labels.openSheet}
          <i className="fa-solid fa-arrow-right ms-2" aria-hidden="true" />
        </a>
        <button
          type="button"
          className="btn btn-outline-secondary d-none d-lg-inline-flex inventory-panel-close"
          aria-label={labels.closeSheet}
          title={labels.closeSheet}
          onClick={onClose}
        >
          <i className="fa-solid fa-xmark" aria-hidden="true" />
        </button>
      </div>
      <div className="small text-body-secondary mb-4">
        {labels.openSheetHint}
      </div>

      <div className="d-flex flex-column gap-4">
        <div className="d-flex gap-3 align-items-start">
          <img
            src={product.image || placeholderImage}
            alt=""
            width={PHOTO_SIZE}
            height={PHOTO_SIZE}
            className="rounded border bg-white flex-shrink-0"
            style={{ objectFit: 'contain' }}
          />
          <div className="min-w-0">
            <h2 className="h5 mb-1" ref={heading} tabIndex={-1}>
              {product.name}
            </h2>
            {groupPath && (
              <div className="small text-body-secondary">{groupPath}</div>
            )}
          </div>
        </div>

        {product.in_inventory ? (
          <StockEditor
            key={product.barcode}
            product={product}
            labels={labels}
            languageCode={languageCode}
            onCount={onCountStock}
          />
        ) : (
          <div>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => onToggleInventory(product)}
            >
              <i className="fa-solid fa-plus me-2" aria-hidden="true" />
              {labels.addToInventory}
            </button>
          </div>
        )}

        <section className="border-top pt-4 d-flex flex-column gap-3">
          <h3 className="h6 text-uppercase text-body-secondary fw-semibold mb-0 small">
            {labels.theProduct}
          </h3>
          <dl className="inventory-details small mb-0">
            {packageText && (
              <>
                <dt>{labels.package}</dt>
                <dd>{packageText}</dd>
              </>
            )}
            {product.serving && (
              <>
                <dt>{labels.serving}</dt>
                <dd>{describeServing(product.serving, languageCode)}</dd>
              </>
            )}
            <dt>{labels.createdAt}</dt>
            <dd>
              {new Date(product.created_at).toLocaleDateString(languageCode)}
            </dd>
          </dl>
          <div>
            <div className="small text-body-secondary mb-1">
              {labels.barcode}
            </div>
            <Barcode
              code={product.barcode}
              label={labels.barcode}
              width={BARCODE_WIDTH}
            />
          </div>
        </section>

        {product.in_inventory && (
          <section className="border-top pt-4 d-flex flex-column gap-2">
            <div>
              <button
                type="button"
                className="btn btn-outline-secondary"
                onClick={() => onToggleInventory(product)}
              >
                {labels.removeFromInventory}
              </button>
            </div>
            <div className="small text-body-secondary">
              {labels.removeFromInventoryHint}
            </div>
          </section>
        )}

        {canDelete && (
          <section className="border-top pt-4 d-flex flex-column gap-2">
            <h3 className="h6 text-uppercase text-body-secondary fw-semibold mb-0 small">
              {labels.adminZone}
            </h3>
            <form
              method="post"
              action={productDeleteUrl(product.barcode)}
              onSubmit={(event) => {
                const message = labels.confirmDelete.replace(
                  '%(name)s',
                  product.name,
                );
                if (!window.confirm(message)) {
                  event.preventDefault();
                }
              }}
            >
              <input
                type="hidden"
                name="csrfmiddlewaretoken"
                value={csrfToken}
              />
              <button type="submit" className="btn btn-outline-danger">
                <i
                  className="fa-regular fa-trash-can me-2"
                  aria-hidden="true"
                />
                {labels.deleteFromCatalogue}
              </button>
            </form>
            <div className="small text-body-secondary">
              {labels.deleteFromCatalogueHint}
            </div>
          </section>
        )}
      </div>
    </aside>
  );
}
