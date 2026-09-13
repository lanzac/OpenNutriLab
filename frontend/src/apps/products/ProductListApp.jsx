import { useEffect, useState } from 'react';

import { fetchProducts, getCsrfToken } from './api/client.js';

// Django's edit/delete class-based views still own these URLs (see
// /app/products/urls.py) - React only needs to build links to them.
// Product.barcode is the model's primary key (see /app/products/models.py),
// matching the <str:pk> URL parameter.
const productEditUrl = (barcode) => `/products/${barcode}/edit/`;
const productDeleteUrl = (barcode) => `/products/${barcode}/delete/`;

export function ProductListApp() {
  const [products, setProducts] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    fetchProducts()
      .then((data) => {
        if (!cancelled) setProducts(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return <p className="text-danger">{error}</p>;
  }

  if (products === null) {
    return <p>Loading…</p>;
  }

  if (products.length === 0) {
    return null;
  }

  return (
    <table className="table table-striped">
      <thead>
        <tr>
          <th>Product name</th>
          <th>Created at</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {products.map((product) => (
          <tr key={product.barcode}>
            <td>{product.name}</td>
            <td>{new Date(product.created_at).toLocaleDateString()}</td>
            <td>
              <div className="btn-toolbar" role="toolbar">
                <a
                  className="btn btn-warning me-2"
                  href={productEditUrl(product.barcode)}
                >
                  <i className="fa-regular fa-pen-to-square" /> Edit
                </a>
                <form
                  method="post"
                  action={productDeleteUrl(product.barcode)}
                  className="d-inline"
                  onSubmit={(event) => {
                    if (!window.confirm(`Delete "${product.name}"?`)) {
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
                    <i className="fa-regular fa-trash-can" /> Delete
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
