// The search of OpenFoodFacts on the page that creates a product (see
// templates/products/components/off_search.html): a name or a brand typed, the
// products found listed, and the one chosen loaded the way a barcode typed is.
import './off-search.css';

import { reloadWith } from './barcode-actions.js';

// How long a person must stop typing before OpenFoodFacts is asked.
const PAUSE = 400;

/** The line a product is listed by: what tells it from the others that share its name. */
function detailOf(hit) {
  return [hit.brands, hit.quantity, hit.barcode].filter(Boolean).join(' · ');
}

function itemOf(hit, placeholder) {
  const item = document.createElement('li');
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'list-group-item list-group-item-action';

  const image = document.createElement('img');
  image.className = 'off-hit-image';
  image.alt = '';
  image.loading = 'lazy';
  image.src = hit.image || placeholder;

  const text = document.createElement('span');
  text.className = 'off-hit-text';
  const name = document.createElement('span');
  name.className = 'off-hit-name d-block';
  name.textContent = hit.name || hit.barcode;
  const detail = document.createElement('span');
  detail.className = 'off-hit-detail d-block';
  detail.textContent = detailOf(hit);
  text.append(name, detail);

  button.append(image, text);
  button.addEventListener('click', () => reloadWith('barcode', hit.barcode));
  item.append(button);
  return item;
}

/**
 * @param {{ url: string, minLength: number, placeholderImage: string,
 *   labels: { searching: string, none: string, error: string } }} config Built server-side (see
 *   product_form_config in opennutrilab/products/views.py).
 */
export function initOffSearch(config) {
  const input = document.getElementById('off-search-input');
  const status = document.getElementById('off-search-status');
  const results = document.getElementById('off-search-results');
  if (!input || !status || !results || !config) return;

  let timer = null;
  let request = null;

  const reset = (message = '') => {
    status.textContent = message;
    results.replaceChildren();
  };

  async function search(text) {
    request?.abort();
    request = new AbortController();
    reset(config.labels.searching);
    try {
      const response = await fetch(
        `${config.url}?${new URLSearchParams({ q: text })}`,
        {
          headers: { Accept: 'application/json' },
          credentials: 'same-origin',
          signal: request.signal,
        },
      );
      if (!response.ok) throw new Error(`Search answered ${response.status}`);
      const { results: hits } = await response.json();
      reset(hits.length === 0 ? config.labels.none : '');
      results.append(
        ...hits.map((hit) => itemOf(hit, config.placeholderImage)),
      );
    } catch (error) {
      // A search replaced by a newer one is not a failure.
      if (error.name === 'AbortError') return;
      console.error(error);
      reset(config.labels.error);
    }
  }

  const textOf = () => input.value.trim();
  const longEnough = () => textOf().length >= config.minLength;

  input.addEventListener('input', () => {
    clearTimeout(timer);
    if (!longEnough()) {
      request?.abort();
      reset();
      return;
    }
    timer = setTimeout(() => search(textOf()), PAUSE);
  });

  // Enter searches without waiting, and does not send the form.
  input.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    clearTimeout(timer);
    if (longEnough()) search(textOf());
  });
}
