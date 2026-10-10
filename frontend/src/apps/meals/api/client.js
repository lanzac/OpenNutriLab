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

// The limits are saved as they are changed. They are written one after the other, so
// that the last change of a product is the last the server hears of; and a day is not
// proposed before the limits it should follow are written.
let writing = Promise.resolve();

const afterWrites = (send) => {
  const written = writing.then(send);
  writing = written.catch(() => {});
  return written;
};

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

// Marks a meal of a day as eaten, or as not eaten again.
export const setMealEaten = (day, kind, eaten, csrfToken) =>
  request(`${MEALS_API_BASE}${day}/${kind}`, {
    method: 'PATCH',
    body: { eaten },
    csrfToken,
  });

// What to add to a day, from the inventory, keeping the meals eaten: nothing is
// written until it is taken.
export const proposeDay = (day, csrfToken) =>
  writing.then(() =>
    request(`${MEALS_API_BASE}${day}/propose`, { method: 'POST', csrfToken }),
  );

// Puts the proposed items in place of the day's meals.
export const replaceDay = (day, items, csrfToken) =>
  request(`${MEALS_API_BASE}${day}`, {
    method: 'PUT',
    body: { items },
    csrfToken,
  });

// What the user allows of each product when a day is proposed.
export const fetchLimits = () => request(`${MEALS_API_BASE}limits/`);

export const setLimits = (barcode, limits, csrfToken) =>
  afterWrites(() =>
    request(`${MEALS_API_BASE}limits/${barcode}`, {
      method: 'PUT',
      body: limits,
      csrfToken,
    }),
  );

// Every product of the inventory left out of the days proposed, or put back in.
export const setAllEnabled = (enabled, csrfToken) =>
  afterWrites(() =>
    request(`${MEALS_API_BASE}limits/`, {
      method: 'PUT',
      body: { enabled },
      csrfToken,
    }),
  );

// What to get for the inventory to meet the needs: foods of the CIQUAL table, with
// the day they make. Nothing is written.
export const suggestFoods = (day, csrfToken) =>
  writing.then(() =>
    request(`${MEALS_API_BASE}${day}/suggest`, { method: 'POST', csrfToken }),
  );
