// Thin fetch wrapper for the django-ninja products API (see
// /app/products/api/api_ninja_crud.py, mounted at /api-ninja/products/).
// Kept dependency-free on purpose: nothing here needs caching/invalidation
// yet, so plain fetch is simpler than pulling in a data-fetching library.
//
// No CSRF helper here: CSRF_COOKIE_HTTPONLY keeps the token out of
// document.cookie, so it is handed down from Django instead (see
// ProductListView).

const PRODUCTS_API_BASE = '/api-ninja/products/';

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
