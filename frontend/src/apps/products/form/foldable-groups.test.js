import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { initFoldableGroups } from './foldable-groups.js';

const STORAGE_KEY = 'products.formGroups';

// What the server writes (see crispy_bootstrap_extend/foldable-group.html).
function group(key, { open = false, values = [], invalid = false } = {}) {
  const inputs = (values.length ? values : ['']).map(
    (value, index) =>
      `<input id="${key}-${index}" value="${value}"${invalid ? ' class="is-invalid"' : ''}>`,
  );
  return `
    <div class="foldable-group" data-fold-group="${key}">
      <button type="button" class="group-toggle${open ? '' : ' collapsed'}"
              aria-expanded="${open}">
        <span data-fold-summary></span>
      </button>
      <div id="nutrients-${key}" class="collapse${open ? ' show' : ''}">${inputs.join('')}</div>
    </div>`;
}

const shown = (key) =>
  document
    .querySelector(`[data-fold-group="${key}"] .collapse`)
    .classList.contains('show');
const summary = (key) =>
  document.querySelector(`[data-fold-group="${key}"] [data-fold-summary]`)
    .textContent;
const toggle = (key) =>
  document.querySelector(`[data-fold-group="${key}"] .group-toggle`);

function mount(...groups) {
  document.body.innerHTML = `<form id="product-form">${groups.join('')}</form>`;
  initFoldableGroups();
}

/** What Bootstrap sends once a group has finished opening or closing. */
const finish = (key, event) =>
  document
    .querySelector(`[data-fold-group="${key}"] .collapse`)
    .dispatchEvent(new Event(`${event}.bs.collapse`, { bubbles: true }));

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  document.body.innerHTML = '';
  window.localStorage.clear();
});

describe('initFoldableGroups', () => {
  it('says how many of the figures of a group hold a value, as they are typed', () => {
    mount(group('vitamin', { values: ['', '12', ' '] }));
    expect(summary('vitamin')).toBe('1 / 3');

    const first = document.getElementById('vitamin-0');
    first.value = '3';
    first.dispatchEvent(new Event('input', { bubbles: true }));

    expect(summary('vitamin')).toBe('2 / 3');
  });

  it('keeps what a person chose, and opens it the same next time', () => {
    mount(group('macronutrient', { open: true }), group('vitamin'));

    finish('macronutrient', 'hidden');
    finish('vitamin', 'shown');

    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY))).toEqual({
      macronutrient: false,
      vitamin: true,
    });

    mount(group('macronutrient', { open: true }), group('vitamin'));
    expect(shown('macronutrient')).toBe(false);
    expect(toggle('macronutrient')).toHaveAttribute('aria-expanded', 'false');
    expect(toggle('macronutrient')).toHaveClass('collapsed');
    expect(shown('vitamin')).toBe(true);
    expect(toggle('vitamin')).toHaveAttribute('aria-expanded', 'true');
    expect(toggle('vitamin')).not.toHaveClass('collapsed');
  });

  it('does not take for a choice what the page did itself', () => {
    mount(group('vitamin'));

    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('leaves a group open that has a figure to put right, whatever was chosen', () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ vitamin: false }),
    );

    mount(group('vitamin', { open: true, invalid: true }));

    expect(shown('vitamin')).toBe(true);
  });

  it('opens a closed group whose figure the browser refuses', () => {
    mount(group('vitamin'));
    expect(shown('vitamin')).toBe(false);

    document
      .getElementById('vitamin-0')
      .dispatchEvent(new Event('invalid', { bubbles: false }));

    expect(shown('vitamin')).toBe(true);
    expect(toggle('vitamin')).toHaveAttribute('aria-expanded', 'true');
  });

  it('works without storage, and with what is not a choice in it', () => {
    window.localStorage.setItem(STORAGE_KEY, '["not", "an", "object"]');
    expect(() => mount(group('vitamin', { open: true }))).not.toThrow();
    expect(shown('vitamin')).toBe(true);

    window.localStorage.setItem(STORAGE_KEY, '{broken');
    expect(() => mount(group('vitamin'))).not.toThrow();
    expect(shown('vitamin')).toBe(false);
  });

  it('does nothing on a page without groups', () => {
    document.body.innerHTML = '<form id="product-form"></form>';

    expect(() => initFoldableGroups()).not.toThrow();
  });
});
