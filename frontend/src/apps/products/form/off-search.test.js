import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { reloadWith } from './barcode-actions.js';
import { initOffSearch } from './off-search.js';

vi.mock('./barcode-actions.js', () => ({ reloadWith: vi.fn() }));

const CONFIG = {
  url: '/products/search-off/',
  minLength: 3,
  placeholderImage: '/static/milk.png',
  labels: {
    searching: 'Recherche…',
    none: 'Aucun produit.',
    error: 'Injoignable.',
  },
};

const HIT = {
  barcode: '3700966568466',
  name: 'Colin d’Alaska pané',
  brands: 'Cap océan',
  quantity: '500 g',
  image: 'https://images.openfoodfacts.org/a.jpg',
};

function answer(results, ok = true) {
  return vi.fn().mockResolvedValue({
    ok,
    status: ok ? 200 : 502,
    json: async () => ({ results }),
  });
}

const input = () => document.getElementById('off-search-input');
const status = () => document.getElementById('off-search-status');
const hits = () => document.querySelectorAll('#off-search-results button');

/** What a person does: types, and stops typing. */
async function type(text) {
  input().value = text;
  input().dispatchEvent(new Event('input', { bubbles: true }));
  await vi.advanceTimersByTimeAsync(500);
}

beforeEach(() => {
  vi.useFakeTimers();
  document.body.innerHTML = `
    <form id="product-form">
      <input type="search" id="off-search-input">
      <div id="off-search-status"></div>
      <ul id="off-search-results"></ul>
    </form>`;
  initOffSearch(CONFIG);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('initOffSearch', () => {
  it('lists the products a name finds, said apart by brand, quantity and barcode', async () => {
    const fetch = answer([HIT]);
    vi.stubGlobal('fetch', fetch);

    await type('colin pané');

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe(
      '/products/search-off/?q=colin+pan%C3%A9',
    );
    expect(hits()).toHaveLength(1);
    expect(hits()[0].querySelector('.off-hit-name').textContent).toBe(
      'Colin d’Alaska pané',
    );
    expect(hits()[0].querySelector('.off-hit-detail').textContent).toBe(
      'Cap océan · 500 g · 3700966568466',
    );
    expect(hits()[0].querySelector('img').getAttribute('src')).toBe(HIT.image);
    expect(status().textContent).toBe('');
  });

  it('shows a picture in place of one a product does not have', async () => {
    vi.stubGlobal('fetch', answer([{ ...HIT, image: '' }]));

    await type('colin');

    expect(hits()[0].querySelector('img').getAttribute('src')).toBe(
      '/static/milk.png',
    );
  });

  it('asks once a person has stopped typing, not at each key', async () => {
    const fetch = answer([HIT]);
    vi.stubGlobal('fetch', fetch);

    input().value = 'col';
    input().dispatchEvent(new Event('input'));
    await vi.advanceTimersByTimeAsync(200);
    input().value = 'colin';
    input().dispatchEvent(new Event('input'));
    await vi.advanceTimersByTimeAsync(200);
    expect(fetch).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(300);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toContain('q=colin');
  });

  it('does not ask for a text too short, and clears what was listed', async () => {
    const fetch = answer([HIT]);
    vi.stubGlobal('fetch', fetch);
    await type('colin');
    expect(hits()).toHaveLength(1);

    await type('co');

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(hits()).toHaveLength(0);
    expect(status().textContent).toBe('');
  });

  it('says so when nothing is found', async () => {
    vi.stubGlobal('fetch', answer([]));

    await type('zzzzzz');

    expect(hits()).toHaveLength(0);
    expect(status().textContent).toBe('Aucun produit.');
  });

  it('says so when OpenFoodFacts cannot be reached', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.stubGlobal('fetch', answer([], false));

    await type('colin');

    expect(status().textContent).toBe('Injoignable.');
  });

  it('loads the product chosen the way a barcode typed is', async () => {
    vi.stubGlobal('fetch', answer([HIT]));
    await type('colin');

    hits()[0].click();

    expect(reloadWith).toHaveBeenCalledWith('barcode', '3700966568466');
  });

  it('searches at once on Enter, and does not send the form', async () => {
    const fetch = answer([HIT]);
    vi.stubGlobal('fetch', fetch);
    input().value = 'colin';

    const enter = new KeyboardEvent('keydown', {
      key: 'Enter',
      bubbles: true,
      cancelable: true,
    });
    input().dispatchEvent(enter);
    await vi.advanceTimersByTimeAsync(0);

    expect(enter.defaultPrevented).toBe(true);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('shows the last search only when two overlap', async () => {
    const answers = [];
    const fetch = vi.fn(
      (_url, { signal }) =>
        new Promise((resolve, reject) => {
          answers.push(resolve);
          signal.addEventListener('abort', () =>
            reject(new DOMException('aborted', 'AbortError')),
          );
        }),
    );
    vi.stubGlobal('fetch', fetch);

    await type('colin');
    await type('saumon');
    // The first was abandoned; only the second can be answered.
    answers[1]({
      ok: true,
      status: 200,
      json: async () => ({ results: [{ ...HIT, name: 'Saumon' }] }),
    });
    await vi.advanceTimersByTimeAsync(0);

    expect(hits()).toHaveLength(1);
    expect(hits()[0].querySelector('.off-hit-name').textContent).toBe('Saumon');
    expect(status().textContent).toBe('');
  });
});
