import { Barcode } from './Barcode.jsx';
import { StockCell } from './StockCell.jsx';
import { describePackage } from './stockUnits.js';

// Django's edit/delete class-based views still own these URLs (see
// opennutrilab/products/urls.py) - React only needs to build links to them.
// Product.barcode is the model's primary key (see opennutrilab/products/models.py),
// matching the <str:pk> URL parameter.
const productEditUrl = (barcode) => `/products/${barcode}/edit/`;
const productDeleteUrl = (barcode) => `/products/${barcode}/delete/`;

// The side of the square a photo is shown in. The stored photos are small
// (OpenFoodFacts' own sizes), so the browser scales them, none is cut.
const THUMBNAIL_SIZE = 56;

/**
 * One product of the list: its photo, name, barcode and quantity, and the few
 * things that can be done with it, as small icon buttons that say what they do
 * when pointed at (and to screen readers) rather than a row of big labelled ones.
 *
 * @param {object} props
 * @param {object} props.product A product of the products API.
 * @param {Record<string, string>} props.labels Translated by ProductListView.
 * @param {string} props.csrfToken For the delete form, a plain POST to Django.
 * @param {string} props.languageCode The language Django is serving.
 * @param {boolean} props.canDelete True for staff only.
 * @param {string} props.placeholderImage Shown for a product with no photo.
 * @param {(product: object) => void} props.onToggleInventory
 * @param {(product: object, quantity: number | null, unit: string) => Promise<void>} props.onCountStock
 */
export function ProductRow({
  product,
  labels,
  csrfToken,
  languageCode,
  canDelete,
  placeholderImage,
  onToggleInventory,
  onCountStock,
}) {
  const inventoryLabel = product.in_inventory
    ? labels.removeFromInventory
    : labels.addToInventory;

  return (
    <tr>
      <td>
        {/* The name is in the next cell: the picture adds nothing to it. */}
        <img
          src={product.image || placeholderImage}
          alt=""
          width={THUMBNAIL_SIZE}
          height={THUMBNAIL_SIZE}
          className="rounded border bg-white d-block"
          style={{ objectFit: 'contain' }}
          loading="lazy"
        />
      </td>
      <td className="fw-semibold">{product.name}</td>
      {/* Hidden on a phone, which is what scans a barcode, and where the room is
          wanted for the name and the actions. */}
      <td className="d-none d-md-table-cell">
        <Barcode code={product.barcode} label={labels.barcode} />
      </td>
      <td className="text-nowrap d-none d-sm-table-cell">
        {describePackage(product, labels, languageCode)}
      </td>
      <StockCell
        product={product}
        labels={labels}
        languageCode={languageCode}
        onCount={onCountStock}
      />
      <td className="text-nowrap text-body-secondary d-none d-md-table-cell">
        {new Date(product.created_at).toLocaleDateString(languageCode)}
      </td>
      <td>
        <div
          className="d-flex justify-content-end gap-1"
          role="toolbar"
          aria-label={labels.editAndDelete}
        >
          <button
            type="button"
            className={`btn btn-sm ${
              product.in_inventory
                ? 'btn-outline-success'
                : 'btn-outline-secondary'
            }`}
            title={inventoryLabel}
            aria-label={inventoryLabel}
            onClick={() => onToggleInventory(product)}
          >
            <i
              className={`fa-solid ${product.in_inventory ? 'fa-check' : 'fa-plus'}`}
            />
          </button>
          <a
            className="btn btn-sm btn-outline-secondary"
            href={productEditUrl(product.barcode)}
            title={labels.edit}
            aria-label={labels.edit}
          >
            <i className="fa-regular fa-pen-to-square" />
          </a>
          {canDelete && (
            <form
              method="post"
              action={productDeleteUrl(product.barcode)}
              className="d-inline"
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
              <button
                type="submit"
                className="btn btn-sm btn-outline-danger"
                title={labels.delete}
                aria-label={labels.delete}
              >
                <i className="fa-regular fa-trash-can" />
              </button>
            </form>
          )}
        </div>
      </td>
    </tr>
  );
}
