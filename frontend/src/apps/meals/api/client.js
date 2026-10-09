// Thin fetch wrapper for the meals API (see opennutrilab/meals/api/routes.py,
// mounted at /api/v1/meals/ by config/api.py) and the user's inventory.
//
// Every write answers with the whole day it changed, which the page shows as it
// is: the totals are worked out by the server, never here.
//
// CSRF_COOKIE_HTTPONLY keeps the token out of document.cookie, so the writes
// take it from the caller, which Django handed it to (see MealsView).

const MEALS_API_BASE = '/api/v1/meals/';
const INVENTORY_API = '/api/v1/inventory/';

async function request(url, { method = 'GET', body, csrfToken } = {}) {
  const headers = { Accept: 'application/json' };
  if (method !== 'GET') headers['X-CSRFToken'] = csrfToken;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    // Technical message: the page shows a translated one to the user.
    const error = new Error(
      `${method} ${url} failed (HTTP ${response.status})`,
    );
    error.status = response.status;
    throw error;
  }
  return response.json();
}

export const fetchDay = (day) => request(`${MEALS_API_BASE}${day}`);

export const fetchInventory = () => request(INVENTORY_API);

export const addItem = (day, kind, item, csrfToken) =>
  request(`${MEALS_API_BASE}${day}/${kind}/items`, {
    method: 'POST',
    body: item,
    csrfToken,
  });

export const changeItem = (id, change, csrfToken) =>
  request(`${MEALS_API_BASE}items/${id}`, {
    method: 'PATCH',
    body: change,
    csrfToken,
  });

export const removeItem = (id, csrfToken) =>
  request(`${MEALS_API_BASE}items/${id}`, { method: 'DELETE', csrfToken });
