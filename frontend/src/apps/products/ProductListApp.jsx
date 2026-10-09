import { useEffect, useMemo, useState } from 'react';

import { fetchProducts, setInInventory } from './api/client.js';
import { groupProducts } from './groups.js';
import { ProductRow } from './ProductRow.jsx';

// Photo, name, barcode, quantity, date, actions.
const COLUMNS = 6;

/**
 * Renders the inventory: the user's own, or every product of the shared
 * catalogue, cut into the food groups the products are filed under (a group
 * folds away, a group with subgroups titles them), each product a row with a
 * button to put it in the inventory or take it out.
 *
 * Everything the server owes this component arrives through a |json_script
 * blob (see ProductListView): `labels` already translated, so the .po
 * catalogue stays the single source of truth; `groupNames`, the names of the
 * food groups in the language served; `csrfToken`, which cannot come
 * from the cookie because CSRF_COOKIE_HTTPONLY hides it from JS; and
 * `languageCode`, so dates follow the language Django is serving rather than
 * the browser's own locale; and `canDelete`, true for staff only, who are
 * the only ones the server lets delete (see ProductDeleteView); and
 * `placeholderImage`, the static picture shown for a product that has no photo
 * (a static URL is only known to Django, it carries the deployment's hash).
 */
export function ProductListApp({
  labels,
  groupNames,
  csrfToken,
  languageCode,
  canDelete,
  placeholderImage,
}) {
  const [products, setProducts] = useState(null);
  const [error, setError] = useState(null);
  const [showAll, setShowAll] = useState(false);
  const [inventoryError, setInventoryError] = useState(false);
  // The groups the user has folded away, by key.
  const [folded, setFolded] = useState(() => new Set());

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

  const shown = useMemo(
    () => (showAll ? products : products?.filter((p) => p.in_inventory)),
    [products, showAll],
  );
  const groups = useMemo(
    () =>
      shown &&
      groupProducts(shown, {
        names: groupNames ?? {},
        uncategorised: labels.uncategorised,
        locale: languageCode,
      }),
    [shown, groupNames, labels.uncategorised, languageCode],
  );

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

  const toggleFolded = (key) =>
    setFolded((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  const rowProps = {
    labels,
    csrfToken,
    languageCode,
    canDelete,
    placeholderImage,
    onToggleInventory: toggleInventory,
  };

  return (
    <>
      <div className="btn-group btn-group-sm mb-3" role="group">
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
      {groups.length === 0 ? (
        <p>{labels.inventoryEmpty}</p>
      ) : (
        <div className="table-responsive">
          <table className="table table-hover align-middle">
            <thead className="small text-uppercase text-body-secondary">
              <tr>
                <th scope="col">
                  <span className="visually-hidden">{labels.image}</span>
                </th>
                <th scope="col">{labels.productName}</th>
                <th scope="col" className="d-none d-md-table-cell">
                  {labels.barcode}
                </th>
                <th scope="col" className="d-none d-sm-table-cell">
                  {labels.totalQuantity}
                </th>
                <th scope="col" className="d-none d-md-table-cell">
                  {labels.createdAt}
                </th>
                <th scope="col" className="text-end">
                  {labels.actions}
                </th>
              </tr>
            </thead>
            {groups.map((group) => {
              const open = !folded.has(group.key);
              return (
                <tbody key={group.key || 'unclassified'}>
                  <tr>
                    <th
                      scope="colgroup"
                      colSpan={COLUMNS}
                      className="bg-body-tertiary"
                    >
                      <button
                        type="button"
                        className="btn btn-link p-0 d-flex align-items-center gap-2 w-100 text-start text-reset text-decoration-none fw-semibold"
                        aria-expanded={open}
                        onClick={() => toggleFolded(group.key)}
                      >
                        <i
                          className={`fa-solid fa-chevron-${open ? 'down' : 'right'} small`}
                        />
                        {group.name}
                        <span className="badge rounded-pill text-bg-secondary">
                          {group.count}
                        </span>
                      </button>
                    </th>
                  </tr>
                  {open &&
                    group.subgroups.map((subgroup) => (
                      <SubgroupRows
                        key={subgroup.key || 'unclassified'}
                        subgroup={subgroup}
                        titled={group.titled}
                        rowProps={rowProps}
                      />
                    ))}
                </tbody>
              );
            })}
          </table>
        </div>
      )}
    </>
  );
}

// The rows of one subgroup, under a title of its own when its group has titled ones.
function SubgroupRows({ subgroup, titled, rowProps }) {
  return (
    <>
      {titled && (
        <tr>
          <th
            scope="colgroup"
            colSpan={COLUMNS}
            className="ps-4 small text-body-secondary fw-semibold"
          >
            {subgroup.name}
          </th>
        </tr>
      )}
      {subgroup.products.map((product) => (
        <ProductRow key={product.barcode} product={product} {...rowProps} />
      ))}
    </>
  );
}
