// Thin fetch wrapper for the django-ninja products API (see
// opennutrilab/products/api/routes.py, mounted at /api/v1/products/ by config/api.py).
// Kept dependency-free on purpose: nothing here needs caching/invalidation
// yet, so plain fetch is simpler than pulling in a data-fetching library.
//
// CSRF_COOKIE_HTTPONLY keeps the CSRF token out of document.cookie, so the
// writes below take it from the caller, which Django handed it to (see
// ProductListView).

const PRODUCTS_API_BASE = '/api/v1/products/';
const INVENTORY_API_BASE = '/api/v1/inventory/';

export async function fetchProducts() {
  const response = await fetch(PRODUCTS_API_BASE, {
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) {
    // Technical message: callers show a translated one to the user (the
    // catalogue lives in Django, see ProductListView).
    throw new Error(
      `GET ${PRODUCTS_API_BASE} failed (HTTP ${response.status})`,
    );
  }
  return response.json();
}

// Counts the stock of a product of the inventory: how much is at hand now, in
// the unit it is counted in, or null when it is not counted. Answers with the
// inventory item.
export async function setStock(barcode, quantity, unit, csrfToken) {
  const url = `${INVENTORY_API_BASE}${barcode}/stock`;
  const response = await fetch(url, {
    method: 'PUT',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken,
    },
    body: JSON.stringify({ quantity, unit }),
  });
  if (!response.ok) {
    throw new Error(`PUT ${url} failed (HTTP ${response.status})`);
  }
  return response.json();
}

// Puts a product in the user's inventory, or takes it out.
export async function setInInventory(barcode, inInventory, csrfToken) {
  const url = `${INVENTORY_API_BASE}${barcode}`;
  const method = inInventory ? 'PUT' : 'DELETE';
  const response = await fetch(url, {
    method,
    headers: { Accept: 'application/json', 'X-CSRFToken': csrfToken },
  });
  if (!response.ok) {
    throw new Error(`${method} ${url} failed (HTTP ${response.status})`);
  }
}
