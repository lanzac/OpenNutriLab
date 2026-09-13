// Thin fetch wrapper for the django-ninja products API (see
// /app/products/api/api_ninja_crud.py, mounted at /api-ninja/products/).
// Kept dependency-free on purpose: nothing here needs caching/invalidation
// yet, so plain fetch is simpler than pulling in a data-fetching library.

const PRODUCTS_API_BASE = '/api-ninja/products/';

/**
 * Reads a cookie value by name (used for Django's CSRF token, which is
 * needed on the plain HTML <form method="post"> used for delete, since
 * that form isn't going through this fetch client).
 */
export function getCookie(name) {
  const match = document.cookie
    .split('; ')
    .find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split('=').slice(1).join('=')) : '';
}

export function getCsrfToken() {
  return getCookie('csrftoken');
}

export async function fetchProducts() {
  const response = await fetch(PRODUCTS_API_BASE, {
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) {
    throw new Error(`Failed to load products (HTTP ${response.status})`);
  }
  return response.json();
}
