import { useEffect, useMemo, useState } from 'react';

import { useStoredChoice } from '../../shared/useViewState.js';
import { fetchProducts, setInInventory, setStock } from './api/client.js';
import { groupPathOf, groupProducts } from './groups.js';
import './inventory.css';
import { ProductPanel } from './ProductPanel.jsx';
import { ProductRow } from './ProductRow.jsx';
import { ProductScanner } from './scan/ProductScanner.jsx';
import { defaultStockUnit, stockStatus } from './stockUnits.js';

const VIEWS = ['mine', 'all'];
const FILTERS = ['all', 'in-stock', 'used-up', 'uncounted'];

// The stock filter that keeps the products a status says.
const FILTER_STATUS = {
  'in-stock': 'counted',
  'used-up': 'used-up',
  uncounted: 'uncounted',
};

// The query parameter the product whose sheet is open is kept in, so that a refresh
// (or a link) comes back to it.
const PRODUCT_PARAM = 'product';

/** Text as it is searched: without accents or case ("Pâtes" is found by "pates"). */
const searchable = (text) =>
  text
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase();

function readSelectedBarcode() {
  return new URLSearchParams(window.location.search).get(PRODUCT_PARAM);
}

function writeSelectedBarcode(barcode) {
  const url = new URL(window.location.href);
  if (barcode) url.searchParams.set(PRODUCT_PARAM, barcode);
  else url.searchParams.delete(PRODUCT_PARAM);
  window.history.replaceState(window.history.state, '', url);
}

/**
 * Renders the inventory: the user's own, or every product of the shared
 * catalogue, cut into the food groups the products are filed under (a group
 * folds away, a group with subgroups titles them), each product a line that says
 * where its stock stands. A product opens as a sheet beside the list (over it on a
 * phone), where its stock is counted and where it is taken out of the inventory.
 * The user's own inventory can be narrowed to what is in stock, used up or not
 * counted, and every list searched by name.
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
  const [inventoryError, setInventoryError] = useState(false);
  // What the user looks at, kept from one visit to the next.
  const [view, setView] = useStoredChoice('products.inventoryView', VIEWS);
  const [filter, setFilter] = useStoredChoice('products.stockFilter', FILTERS);
  const [query, setQuery] = useState('');
  // The barcode of the product whose sheet is open.
  const [selected, setSelected] = useState(readSelectedBarcode);
  // The groups the user has folded away, by key.
  const [folded, setFolded] = useState(() => new Set());
  // Whether the camera that scans products into the inventory is open.
  const [scanning, setScanning] = useState(false);

  const select = (barcode) => {
    setSelected(barcode);
    writeSelectedBarcode(barcode);
  };

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

  const inView = useMemo(
    () => (view === 'all' ? products : products?.filter((p) => p.in_inventory)),
    [products, view],
  );

  // How many products each stock filter keeps, for the chips to say.
  const counts = useMemo(() => {
    const found = { all: 0, 'in-stock': 0, 'used-up': 0, uncounted: 0 };
    for (const product of inView ?? []) {
      found.all += 1;
      const status = stockStatus(product);
      const key = Object.keys(FILTER_STATUS).find(
        (name) => FILTER_STATUS[name] === status,
      );
      if (key) found[key] += 1;
    }
    return found;
  }, [inView]);

  // The filter is on the user's inventory only: a product outside it has no stock.
  const filtering = view === 'mine' && filter !== 'all';
  const shown = useMemo(() => {
    const wanted = searchable(query.trim());
    return inView?.filter(
      (product) =>
        (!filtering || stockStatus(product) === FILTER_STATUS[filter]) &&
        (wanted === '' ||
          searchable(`${product.name} ${product.barcode}`).includes(wanted)),
    );
  }, [inView, filtering, filter, query]);

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

  // The sheet is of a product the list can show: one taken out of the inventory, or
  // not of the list that is looked at, has none.
  const selectedProduct = inView?.find((p) => p.barcode === selected) ?? null;
  useEffect(() => {
    if (inView && selected && !selectedProduct) select(null);
  }, [inView, selected, selectedProduct]);

  if (error) {
    return <p className="text-danger">{labels.loadError}</p>;
  }

  if (products === null) {
    return <p>{labels.loading}</p>;
  }

  if (products.length === 0) {
    return null;
  }

  const patchProduct = (barcode, changes) =>
    setProducts((current) =>
      current.map((p) => (p.barcode === barcode ? { ...p, ...changes } : p)),
    );

  // A product put in the inventory is not counted; one taken out leaves its stock.
  const markInInventory = (barcode, wanted) =>
    setProducts((current) =>
      current.map((p) =>
        p.barcode === barcode
          ? {
              ...p,
              in_inventory: wanted,
              stock: wanted
                ? {
                    quantity: null,
                    unit: defaultStockUnit(p),
                    counted_at: null,
                  }
                : null,
            }
          : p,
      ),
    );

  const toggleInventory = (product) => {
    const wanted = !product.in_inventory;
    setInventoryError(false);
    setInInventory(product.barcode, wanted, csrfToken)
      .then(() => markInInventory(product.barcode, wanted))
      .catch((err) => {
        console.error(err);
        setInventoryError(true);
      });
  };

  // Keeps the stock counted for a product; the server answers with what it holds.
  const countStock = (product, quantity, unit) =>
    setStock(product.barcode, quantity, unit, csrfToken).then((item) =>
      patchProduct(product.barcode, { stock: item.stock }),
    );

  const toggleFolded = (key) =>
    setFolded((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  const rowProps = {
    view,
    labels,
    languageCode,
    placeholderImage,
    onSelect: select,
    onToggleInventory: toggleInventory,
    onCountStock: countStock,
  };

  const filterNames = {
    all: labels.filterAll,
    'in-stock': labels.filterInStock,
    'used-up': labels.filterUsedUp,
    uncounted: labels.filterNotCounted,
  };

  return (
    <>
      <div className="d-flex flex-wrap align-items-center gap-2 mb-3">
        <div className="btn-group" role="group">
          <button
            type="button"
            className={`btn ${view === 'mine' ? 'btn-primary' : 'btn-outline-primary'}`}
            aria-pressed={view === 'mine'}
            onClick={() => setView('mine')}
          >
            {labels.myInventory}
          </button>
          <button
            type="button"
            className={`btn ${view === 'all' ? 'btn-primary' : 'btn-outline-primary'}`}
            aria-pressed={view === 'all'}
            onClick={() => setView('all')}
          >
            {labels.allProducts}
          </button>
        </div>
        <div
          className="position-relative flex-grow-1"
          style={{ maxWidth: '24rem' }}
        >
          <i
            className="fa-solid fa-magnifying-glass position-absolute top-50 translate-middle-y text-body-secondary ms-3"
            aria-hidden="true"
          />
          <input
            type="search"
            className="form-control ps-5"
            aria-label={labels.searchProducts}
            placeholder={labels.searchProducts}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <button
          type="button"
          className="btn btn-outline-primary ms-auto"
          aria-expanded={scanning}
          onClick={() => setScanning((open) => !open)}
        >
          <i className="fa-solid fa-barcode" /> {labels.scanProduct}
        </button>
      </div>
      {view === 'mine' && (
        <div
          className="d-flex flex-wrap gap-2 mb-3"
          role="group"
          aria-label={labels.filterByStock}
        >
          {FILTERS.map((name) => (
            <button
              key={name}
              type="button"
              className={`btn btn-sm rounded-pill ${
                filter === name ? 'btn-secondary' : 'btn-outline-secondary'
              }`}
              aria-pressed={filter === name}
              onClick={() => setFilter(name)}
            >
              {filterNames[name]}{' '}
              <span className={filter === name ? '' : 'text-body-secondary'}>
                {counts[name]}
              </span>
            </button>
          ))}
        </div>
      )}
      {scanning && (
        <ProductScanner
          products={products}
          labels={labels}
          csrfToken={csrfToken}
          onAdded={(barcode) => markInInventory(barcode, true)}
          onClose={() => setScanning(false)}
        />
      )}
      {inventoryError && (
        <p className="text-danger" role="alert">
          {labels.inventoryError}
        </p>
      )}
      <div className="row g-4 align-items-start">
        <div className="col-lg-7 col-xl-8">
          {groups.length === 0 ? (
            <p>
              {inView.length === 0 && view === 'mine'
                ? labels.inventoryEmpty
                : labels.noMatch}
            </p>
          ) : (
            <div className="inventory-groups">
              {groups.map((group) => {
                const open = !folded.has(group.key);
                return (
                  <section key={group.key || 'unclassified'}>
                    <h2 className="h6 mb-2">
                      <button
                        type="button"
                        className="btn btn-link p-0 d-flex align-items-center gap-2 w-100 text-start text-body-secondary text-decoration-none text-uppercase fw-semibold small"
                        aria-expanded={open}
                        onClick={() => toggleFolded(group.key)}
                      >
                        <i
                          className={`fa-solid fa-chevron-${open ? 'down' : 'right'} small`}
                          aria-hidden="true"
                        />
                        {group.name}
                        <span className="badge rounded-pill text-bg-secondary">
                          {group.count}
                        </span>
                      </button>
                    </h2>
                    {open && (
                      <ul className="inventory-group-list">
                        {group.subgroups.map((subgroup) => (
                          <SubgroupRows
                            key={subgroup.key || 'unclassified'}
                            subgroup={subgroup}
                            titled={group.titled}
                            selected={selected}
                            rowProps={rowProps}
                          />
                        ))}
                      </ul>
                    )}
                  </section>
                );
              })}
            </div>
          )}
        </div>
        <div className="col-lg-5 col-xl-4">
          {selectedProduct ? (
            <ProductPanel
              product={selectedProduct}
              groupPath={groupPathOf(selectedProduct, {
                names: groupNames ?? {},
              })}
              labels={labels}
              csrfToken={csrfToken}
              languageCode={languageCode}
              canDelete={canDelete}
              placeholderImage={placeholderImage}
              onClose={() => select(null)}
              onToggleInventory={toggleInventory}
              onCountStock={countStock}
            />
          ) : (
            <div className="inventory-panel-empty d-none d-lg-block">
              {labels.panelEmpty}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

// The lines of one subgroup, under a title of its own when its group has titled ones.
function SubgroupRows({ subgroup, titled, selected, rowProps }) {
  return (
    <>
      {titled && <li className="inventory-subgroup">{subgroup.name}</li>}
      {subgroup.products.map((product) => (
        <ProductRow
          key={product.barcode}
          product={product}
          selected={product.barcode === selected}
          {...rowProps}
        />
      ))}
    </>
  );
}
