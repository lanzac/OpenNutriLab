import { useEffect, useState } from 'react';

import { fetchProducts, setInInventory } from './api/client.js';

// Django's edit/delete class-based views still own these URLs (see
// opennutrilab/products/urls.py) - React only needs to build links to them.
// Product.barcode is the model's primary key (see opennutrilab/products/models.py),
// matching the <str:pk> URL parameter.
const productEditUrl = (barcode) => `/products/${barcode}/edit/`;
const productDeleteUrl = (barcode) => `/products/${barcode}/delete/`;

/**
 * Renders the inventory table: the user's own inventory, or every product of
 * the shared catalogue, each with a button to put it in the inventory or take
 * it out.
 *
 * Everything the server owes this component arrives through a |json_script
 * blob (see ProductListView): `labels` already translated, so the .po
 * catalogue stays the single source of truth; `csrfToken`, which cannot come
 * from the cookie because CSRF_COOKIE_HTTPONLY hides it from JS; and
 * `languageCode`, so dates follow the language Django is serving rather than
 * the browser's own locale; and `canDelete`, true for staff only, who are
 * the only ones the server lets delete (see ProductDeleteView).
 */
export function ProductListApp({ labels, csrfToken, languageCode, canDelete }) {
  const [products, setProducts] = useState(null);
  const [error, setError] = useState(null);
  const [showAll, setShowAll] = useState(false);
  const [inventoryError, setInventoryError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    fetchProducts()
      .then((data) => {
        if (!cancelled) setProducts(data);
      })
      .catch((err) => {
        // The technical detail (status code) is for the console only: the
        // user gets the translated, generic message below.
        console.error(err);
        if (!cancelled) setError(err);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return <p className="text-danger">{labels.loadError}</p>;
  }

  if (products === null) {
    return <p>{labels.loading}</p>;
  }

  if (products.length === 0) {
    return null;
  }

  const toggleInventory = (product) => {
    const wanted = !product.in_inventory;
    setInventoryError(false);
    setInInventory(product.barcode, wanted, csrfToken)
      .then(() => {
        setProducts((current) =>
          current.map((p) =>
            p.barcode === product.barcode ? { ...p, in_inventory: wanted } : p,
          ),
        );
      })
      .catch((err) => {
        console.error(err);
        setInventoryError(true);
      });
  };

  const shown = showAll ? products : products.filter((p) => p.in_inventory);

  return (
    <>
      <div className="btn-group mb-3" role="group">
        <button
          type="button"
          className={`btn ${showAll ? 'btn-outline-primary' : 'btn-primary'}`}
          aria-pressed={!showAll}
          onClick={() => setShowAll(false)}
        >
          {labels.myInventory}
        </button>
        <button
          type="button"
          className={`btn ${showAll ? 'btn-primary' : 'btn-outline-primary'}`}
          aria-pressed={showAll}
          onClick={() => setShowAll(true)}
        >
          {labels.allProducts}
        </button>
      </div>
      {inventoryError && (
        <p className="text-danger" role="alert">
          {labels.inventoryError}
        </p>
      )}
      {shown.length === 0 ? (
        <p>{labels.inventoryEmpty}</p>
      ) : (
        <table className="table table-striped">
          <thead>
            <tr>
              <th>{labels.productName}</th>
              <th>{labels.createdAt}</th>
              <th>{labels.actions}</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((product) => (
              <tr key={product.barcode}>
                <td>{product.name}</td>
                <td>
                  {new Date(product.created_at).toLocaleDateString(
                    languageCode,
                  )}
                </td>
                <td>
                  <div
                    className="btn-toolbar"
                    role="toolbar"
                    aria-label={labels.editAndDelete}
                  >
                    <button
                      type="button"
                      className={`btn me-2 ${
                        product.in_inventory
                          ? 'btn-outline-secondary'
                          : 'btn-outline-success'
                      }`}
                      onClick={() => toggleInventory(product)}
                    >
                      {product.in_inventory ? (
                        <>
                          <i className="fa-solid fa-minus" />{' '}
                          {labels.removeFromInventory}
                        </>
                      ) : (
                        <>
                          <i className="fa-solid fa-plus" />{' '}
                          {labels.addToInventory}
                        </>
                      )}
                    </button>
                    <a
                      className="btn btn-warning me-2"
                      href={productEditUrl(product.barcode)}
                    >
                      <i className="fa-regular fa-pen-to-square" />{' '}
                      {labels.edit}
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
                        <button type="submit" className="btn btn-danger">
                          <i className="fa-regular fa-trash-can" />{' '}
                          {labels.delete}
                        </button>
                      </form>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
