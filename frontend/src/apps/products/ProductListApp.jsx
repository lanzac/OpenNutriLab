import { useEffect, useState } from 'react';

import { fetchProducts, getCsrfToken } from './api/client.js';

// Django's edit/delete class-based views still own these URLs (see
// /app/products/urls.py) - React only needs to build links to them.
// Product.barcode is the model's primary key (see /app/products/models.py),
// matching the <str:pk> URL parameter.
const productEditUrl = (barcode) => `/products/${barcode}/edit/`;
const productDeleteUrl = (barcode) => `/products/${barcode}/delete/`;

/**
 * Renders the inventory table.
 *
 * `labels` holds the already-translated user-facing strings, handed over by
 * the Django template through a |json_script blob (see ProductListView).
 * Keeping the strings server-side means the .po catalogue stays the single
 * source of truth for as long as Django renders the page shell.
 */
export function ProductListApp({ labels }) {
  const [products, setProducts] = useState(null);
  const [error, setError] = useState(null);

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

  return (
    <table className="table table-striped">
      <thead>
        <tr>
          <th>{labels.productName}</th>
          <th>{labels.createdAt}</th>
          <th>{labels.actions}</th>
        </tr>
      </thead>
      <tbody>
        {products.map((product) => (
          <tr key={product.barcode}>
            <td>{product.name}</td>
            <td>{new Date(product.created_at).toLocaleDateString()}</td>
            <td>
              <div
                className="btn-toolbar"
                role="toolbar"
                aria-label={labels.editAndDelete}
              >
                <a
                  className="btn btn-warning me-2"
                  href={productEditUrl(product.barcode)}
                >
                  <i className="fa-regular fa-pen-to-square" /> {labels.edit}
                </a>
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
                    value={getCsrfToken()}
                  />
                  <button type="submit" className="btn btn-danger">
                    <i className="fa-regular fa-trash-can" /> {labels.delete}
                  </button>
                </form>
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
