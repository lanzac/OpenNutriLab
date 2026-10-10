// The label's ingredient list on the product form, with what the parser read of it
// marked, and a way to leave places out of the reading (see
// opennutrilab/templates/products/components/ingredients_text.html).
//
// A person selects a part of the text and leaves it out, or puts it back; the text
// is then read again by the server (ReadLabelView), which answers with the ingredients
// and the places it read them from. Nothing is added to the text: a reading is the
// label's words, and a person can only take places out of it.
//
// Positions are in characters as Python counts them (code points), not in UTF-16
// units as a JavaScript string does, since they travel to and from the parser.

import './ingredients-text.css';

/** @typedef {[number, number]} Place Where it starts, and where it ends (not in it). */

/**
 * The places of the text that are read, and the ones left out, cut in runs that
 * are one thing or the other: read, left out, or neither.
 *
 * @param {number} length Length of the text, in characters.
 * @param {Place[]} used
 * @param {Place[]} ignored
 * @returns {{ start: number, end: number, kind: 'read' | 'ignored' | 'plain' }[]}
 */
export function segmentsOf(length, used, ignored) {
  const clamp = (position) => Math.min(Math.max(position, 0), length);
  const cuts = new Set([0, length]);
  for (const [start, end] of [...used, ...ignored]) {
    cuts.add(clamp(start));
    cuts.add(clamp(end));
  }
  const points = [...cuts].sort((a, b) => a - b);
  const covers = (places, position) =>
    places.some(([start, end]) => start <= position && position < end);

  const segments = [];
  for (let index = 0; index + 1 < points.length; index += 1) {
    const start = points[index];
    const end = points[index + 1];
    const kind = covers(ignored, start)
      ? 'ignored'
      : covers(used, start)
        ? 'read'
        : 'plain';
    const last = segments[segments.length - 1];
    if (last && last.kind === kind) {
      last.end = end;
    } else {
      segments.push({ start, end, kind });
    }
  }
  return segments;
}

/**
 * `places` with `place` added: in order, the ones that touch made one.
 *
 * @param {Place[]} places
 * @param {Place} place
 * @returns {Place[]}
 */
export function addPlace(places, place) {
  const merged = [];
  for (const [start, end] of [...places, place].sort((a, b) => a[0] - b[0])) {
    const last = merged[merged.length - 1];
    if (last && start <= last[1]) {
      last[1] = Math.max(last[1], end);
    } else {
      merged.push([start, end]);
    }
  }
  return merged;
}

/**
 * `places` without what `place` covers.
 *
 * @param {Place[]} places
 * @param {Place} place
 * @returns {Place[]}
 */
export function removePlace(places, place) {
  const [from, to] = place;
  const left = [];
  for (const [start, end] of places) {
    if (end <= from || start >= to) {
      left.push([start, end]);
      continue;
    }
    if (start < from) left.push([start, from]);
    if (end > to) left.push([to, end]);
  }
  return left;
}

/**
 * `place` without the white space at its ends, or null when nothing else is left.
 *
 * @param {string[]} chars The text, one string per character.
 * @param {Place} place
 * @returns {Place | null}
 */
export function trimPlace(chars, [start, end]) {
  let from = Math.max(0, start);
  let to = Math.min(chars.length, end);
  while (from < to && /\s/.test(chars[from])) from += 1;
  while (to > from && /\s/.test(chars[to - 1])) to -= 1;
  return from < to ? [from, to] : null;
}

const lengthOf = (text) => Array.from(text).length;

/**
 * Where in the text a point of the document is, for a view that is made of runs
 * with their start (`data-start`) and length (`data-length`) in characters.
 *
 * @param {HTMLElement} view
 * @param {Node} node
 * @param {number} offset
 * @returns {number}
 */
function positionIn(view, node, offset) {
  if (node === view) {
    const run = view.children[offset];
    return run ? Number(run.dataset.start) : lengthOf(view.textContent ?? '');
  }
  let run = node;
  while (run && run.parentNode !== view) run = run.parentNode;
  if (!run) return 0;
  const start = Number(run.dataset.start);
  if (node === run)
    return offset === 0 ? start : start + Number(run.dataset.length);
  return start + lengthOf((node.textContent ?? '').slice(0, offset));
}

/**
 * The place of the text a person selected in the view, or null for none.
 *
 * @param {HTMLElement} view
 * @param {Selection | null} selection
 * @returns {Place | null}
 */
export function selectedPlace(view, selection) {
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
    return null;
  }
  const range = selection.getRangeAt(0);
  if (!view.contains(range.commonAncestorContainer)) return null;
  const start = positionIn(view, range.startContainer, range.startOffset);
  const end = positionIn(view, range.endContainer, range.endOffset);
  return [Math.min(start, end), Math.max(start, end)];
}

/**
 * Shows the text with its runs marked: `<mark>` for what was read, `<s>` for what
 * the person left out.
 *
 * @param {HTMLElement} view
 * @param {string[]} chars
 * @param {Place[]} used
 * @param {Place[]} ignored
 */
export function renderText(view, chars, used, ignored) {
  const tags = { read: 'mark', ignored: 's', plain: 'span' };
  const runs = segmentsOf(chars.length, used, ignored).map(
    ({ start, end, kind }) => {
      const run = document.createElement(tags[kind]);
      run.dataset.start = String(start);
      run.dataset.length = String(end - start);
      run.textContent = chars.slice(start, end).join('');
      if (kind === 'ignored') run.className = 'text-body-secondary';
      return run;
    },
  );
  view.replaceChildren(...runs);
}

/**
 * @param {{ onRead?: (reading: { rows: object[], ingredients: string, used: Place[], warnings: { message: string, stops: boolean }[] }) => void }} [options]
 *   `onRead` is told each time the text was read again.
 */
export function initIngredientsText({ onRead } = {}) {
  const root = document.getElementById('ingredients-text');
  const view = document.getElementById('ingredients-text-view');
  const tools = document.getElementById('ingredients-text-tools');
  const stateNode = document.getElementById('ingredients-text-state');
  const form = document.getElementById('product-form');
  if (!root || !view || !tools || !stateNode) return;

  const state = JSON.parse(stateNode.textContent);
  const chars = Array.from(state.text);
  const status = document.getElementById('ingredients-text-status');
  const warnings = document.getElementById('ingredients-text-warnings');
  const button = (action) => tools.querySelector(`[data-action="${action}"]`);
  const field = (name) => form?.elements.namedItem(name);

  let selected = null;
  let busy = false;
  let latest = 0;

  function paint() {
    renderText(view, chars, state.used, state.ignored);
    button('clear').hidden = state.ignored.length === 0;
  }

  function refreshButtons() {
    button('ignore').disabled = busy || selected === null;
    button('restore').disabled = busy || selected === null;
    button('clear').disabled = busy;
  }

  function showWarnings(list) {
    warnings.replaceChildren(
      ...list.map(({ message, stops }) => {
        const line = document.createElement('div');
        line.className = stops ? 'text-danger' : 'text-warning-emphasis';
        line.textContent = message;
        return line;
      }),
    );
  }

  // What the form posts: the ingredients as they are read now, from this text.
  function keepInForm(reading) {
    const set = (name, value) => {
      const input = field(name);
      if (input) input.value = value;
    };
    set('off_ingredients', reading.ingredients);
    set('off_ingredients_text', state.text);
    if (!field('off_barcode')?.value) set('off_barcode', state.barcode);
    set('ingredients_ignored', JSON.stringify(state.ignored));
  }

  async function readWithout(ignored) {
    latest += 1;
    const ticket = latest;
    busy = true;
    refreshButtons();
    status.textContent = root.dataset.reading;
    try {
      const response = await fetch(root.dataset.readUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-CSRFToken': field('csrfmiddlewaretoken')?.value ?? '',
        },
        body: JSON.stringify({
          text: state.text,
          language: state.language,
          ignored,
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const reading = await response.json();
      if (ticket !== latest) return;
      state.ignored = ignored;
      state.used = reading.used;
      keepInForm(reading);
      paint();
      showWarnings(reading.warnings);
      status.textContent = '';
      if (onRead) onRead(reading);
    } catch {
      if (ticket !== latest) return;
      status.textContent = root.dataset.failed;
    } finally {
      if (ticket === latest) {
        busy = false;
        refreshButtons();
      }
    }
  }

  function change(edit) {
    const place = selected && trimPlace(chars, selected);
    if (place) readWithout(edit(state.ignored, place));
  }

  button('ignore').addEventListener('click', () => change(addPlace));
  button('restore').addEventListener('click', () => change(removePlace));
  button('clear').addEventListener('click', () => readWithout([]));
  // A press on a button must not take the selection with it.
  tools.addEventListener('mousedown', (event) => event.preventDefault());

  document.addEventListener('selectionchange', () => {
    const place = selectedPlace(view, window.getSelection());
    // A selection elsewhere on the page is not this one's to act on.
    selected = place && trimPlace(chars, place) ? place : null;
    refreshButtons();
  });

  paint();
  tools.hidden = false;
  const legend = document.getElementById('ingredients-text-legend');
  if (legend) legend.hidden = false;
  refreshButtons();
}
