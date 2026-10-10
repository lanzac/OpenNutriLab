import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  addPlace,
  initIngredientsText,
  removePlace,
  renderText,
  segmentsOf,
  selectedPlace,
  trimPlace,
} from './ingredients-text.js';

describe('segmentsOf', () => {
  it('cuts the text into what is read, what is left out, and the rest', () => {
    expect(
      segmentsOf(
        12,
        [
          [0, 4],
          [8, 12],
        ],
        [[5, 7]],
      ),
    ).toEqual([
      { start: 0, end: 4, kind: 'read' },
      { start: 4, end: 5, kind: 'plain' },
      { start: 5, end: 7, kind: 'ignored' },
      { start: 7, end: 8, kind: 'plain' },
      { start: 8, end: 12, kind: 'read' },
    ]);
  });

  it('shows a place left out as left out, though it was read', () => {
    expect(segmentsOf(6, [[0, 6]], [[2, 4]])).toEqual([
      { start: 0, end: 2, kind: 'read' },
      { start: 2, end: 4, kind: 'ignored' },
      { start: 4, end: 6, kind: 'read' },
    ]);
  });

  it('is one run for a text that is nothing but plain', () => {
    expect(segmentsOf(5, [], [])).toEqual([
      { start: 0, end: 5, kind: 'plain' },
    ]);
  });

  it('joins runs of one kind that touch', () => {
    expect(
      segmentsOf(
        6,
        [
          [0, 3],
          [3, 6],
        ],
        [],
      ),
    ).toEqual([{ start: 0, end: 6, kind: 'read' }]);
  });

  it('keeps a place that goes past the text inside it', () => {
    expect(segmentsOf(4, [[2, 90]], [[-3, 1]])).toEqual([
      { start: 0, end: 1, kind: 'ignored' },
      { start: 1, end: 2, kind: 'plain' },
      { start: 2, end: 4, kind: 'read' },
    ]);
  });

  it('has nothing for an empty text', () => {
    expect(segmentsOf(0, [], [])).toEqual([]);
  });
});

describe('addPlace and removePlace', () => {
  it('adds a place in order, and joins the ones that touch or overlap', () => {
    expect(addPlace([[10, 12]], [2, 4])).toEqual([
      [2, 4],
      [10, 12],
    ]);
    expect(
      addPlace(
        [
          [2, 4],
          [10, 12],
        ],
        [4, 10],
      ),
    ).toEqual([[2, 12]]);
    expect(addPlace([[2, 6]], [3, 5])).toEqual([[2, 6]]);
  });

  it('does not change the list it is given', () => {
    const places = [[2, 4]];
    addPlace(places, [3, 9]);
    removePlace(places, [3, 9]);

    expect(places).toEqual([[2, 4]]);
  });

  it('takes a place out of the middle of one, and leaves two', () => {
    expect(removePlace([[0, 10]], [3, 5])).toEqual([
      [0, 3],
      [5, 10],
    ]);
  });

  it('shortens a place at either end, and drops one it covers', () => {
    expect(removePlace([[0, 10]], [0, 4])).toEqual([[4, 10]]);
    expect(removePlace([[0, 10]], [6, 20])).toEqual([[0, 6]]);
    expect(
      removePlace(
        [
          [2, 4],
          [6, 8],
        ],
        [1, 5],
      ),
    ).toEqual([[6, 8]]);
  });

  it('leaves alone the places it does not reach', () => {
    expect(
      removePlace(
        [
          [0, 2],
          [8, 9],
        ],
        [3, 7],
      ),
    ).toEqual([
      [0, 2],
      [8, 9],
    ]);
    expect(removePlace([[0, 2]], [2, 5])).toEqual([[0, 2]]);
  });
});

describe('trimPlace', () => {
  const chars = Array.from(' ab  cd ');

  it('leaves out the white space at its ends', () => {
    expect(trimPlace(chars, [0, 8])).toEqual([1, 7]);
  });

  it('is nothing for a place that is only white space', () => {
    expect(trimPlace(chars, [2, 2])).toBeNull();
    expect(trimPlace(chars, [3, 5])).toBeNull();
  });
});

describe('renderText', () => {
  it('marks what was read, strikes what was left out, and counts in characters', () => {
    const view = document.createElement('div');
    renderText(view, Array.from('ab, cd'), [[0, 2]], [[4, 6]]);

    const runs = [...view.children];
    expect(runs.map((run) => run.tagName)).toEqual(['MARK', 'SPAN', 'S']);
    expect(runs.map((run) => run.textContent)).toEqual(['ab', ', ', 'cd']);
    expect(runs.map((run) => run.dataset.start)).toEqual(['0', '2', '4']);
    expect(runs.map((run) => run.dataset.length)).toEqual(['2', '2', '2']);
  });

  it('never reads the text as HTML', () => {
    const view = document.createElement('div');
    renderText(view, Array.from('<img src=x onerror=alert(1)>'), [[0, 29]], []);

    expect(view.querySelector('img')).toBeNull();
    expect(view.textContent).toBe('<img src=x onerror=alert(1)>');
  });

  it('counts a character outside the basic plane as one', () => {
    const view = document.createElement('div');
    renderText(view, Array.from('a🥛b'), [[1, 2]], []);

    expect(view.children[1].textContent).toBe('🥛');
    expect(view.children[2].dataset.start).toBe('2');
  });
});

describe('selectedPlace', () => {
  let view;

  beforeEach(() => {
    document.body.innerHTML = '<p id="outside">elsewhere</p>';
    view = document.createElement('div');
    document.body.append(view);
    renderText(
      view,
      Array.from('Sucre, a🥛b, sel'),
      [
        [0, 5],
        [7, 10],
      ],
      [],
    );
  });

  afterEach(() => window.getSelection().removeAllRanges());

  const select = (fromNode, from, toNode, to) =>
    window.getSelection().setBaseAndExtent(fromNode, from, toNode, to);

  it('is the place between two points of the text', () => {
    const [first, , third] = [...view.children].map((run) => run.firstChild);

    // Three units into "a🥛b" is after the milk, which is two of them but one character.
    select(first, 2, third, 3);

    expect(selectedPlace(view, window.getSelection())).toEqual([2, 9]);
  });

  it('counts the characters outside the basic plane as one', () => {
    const [, , third] = [...view.children].map((run) => run.firstChild);

    select(third, 1, third, 4);

    // "a🥛b": the milk is one character, so the place is from "🥛" to the end.
    expect(selectedPlace(view, window.getSelection())).toEqual([8, 10]);
  });

  it('is the whole text for a selection of all of it', () => {
    select(view, 0, view, view.childNodes.length);

    expect(selectedPlace(view, window.getSelection())).toEqual([0, 15]);
  });

  it('is null for a selection that is empty', () => {
    select(view.firstChild.firstChild, 2, view.firstChild.firstChild, 2);

    expect(selectedPlace(view, window.getSelection())).toBeNull();
  });

  it('is null for a selection elsewhere in the page', () => {
    const outside = document.getElementById('outside').firstChild;

    select(outside, 0, outside, 4);

    expect(selectedPlace(view, window.getSelection())).toBeNull();
  });

  it('is null for a selection that starts outside the view and ends in it', () => {
    const outside = document.getElementById('outside').firstChild;

    select(outside, 2, view.firstChild.firstChild, 3);

    expect(selectedPlace(view, window.getSelection())).toBeNull();
  });
});

describe('initIngredientsText', () => {
  const TEXT = 'Colin 72% [zone de pêche (FAO 67)], sel.';
  const ZONE = [TEXT.indexOf('['), TEXT.indexOf(']') + 1];
  const reading = (used, warnings = []) => ({
    rows: [{ name: 'colin' }],
    ingredients: '[{"name":"colin"}]',
    used,
    warnings,
  });

  function page({ ignored = [], used = [[0, 9]] } = {}) {
    document.body.innerHTML = `
      <form id="product-form">
        <input type="hidden" name="csrfmiddlewaretoken" value="token-1">
        <input type="hidden" name="off_barcode" value="">
        <input type="hidden" name="off_ingredients" value="">
        <input type="hidden" name="off_ingredients_text" value="">
        <input type="hidden" name="ingredients_ignored" value="[]">
        <div id="ingredients-text" data-read-url="/products/read-label/"
             data-reading="Reading…" data-failed="Failed.">
          <div id="ingredients-text-view"></div>
          <div id="ingredients-text-tools" hidden>
            <button type="button" data-action="ignore" disabled>Leave out</button>
            <button type="button" data-action="restore" disabled>Put back</button>
            <button type="button" data-action="clear" hidden>All back</button>
            <span id="ingredients-text-status"></span>
          </div>
          <div id="ingredients-text-warnings"></div>
          <span id="ingredients-text-legend" hidden>Legend</span>
          <script id="ingredients-text-state" type="application/json"></script>
        </div>
      </form>`;
    document.getElementById('ingredients-text-state').textContent =
      JSON.stringify({
        text: TEXT,
        used,
        ignored,
        language: 'fr',
        barcode: '3017620422003',
      });
  }

  const view = () => document.getElementById('ingredients-text-view');
  const button = (action) =>
    document.querySelector(`[data-action="${action}"]`);
  const hidden = (name) => document.querySelector(`[name="${name}"]`).value;

  function selectText(from, to) {
    // Through the runs, as a person does, whatever they are made of.
    const runs = [...view().children];
    const at = (position) => {
      const run = runs.find(
        (r) =>
          Number(r.dataset.start) <= position &&
          position <= Number(r.dataset.start) + Number(r.dataset.length),
      );
      return [run.firstChild, position - Number(run.dataset.start)];
    };
    const [fromNode, fromOffset] = at(from);
    const [toNode, toOffset] = at(to);
    window
      .getSelection()
      .setBaseAndExtent(fromNode, fromOffset, toNode, toOffset);
    document.dispatchEvent(new Event('selectionchange'));
  }

  const answer = (body, ok = true) =>
    vi.fn().mockResolvedValue({
      ok,
      status: ok ? 200 : 500,
      json: async () => body,
    });

  beforeEach(() => {
    vi.stubGlobal('fetch', answer(reading([[0, 9]])));
  });

  afterEach(() => {
    window.getSelection().removeAllRanges();
    vi.unstubAllGlobals();
  });

  it('shows the text with what was read marked, and the tools', () => {
    page();

    initIngredientsText();

    expect(
      [...view().querySelectorAll('mark')].map((m) => m.textContent),
    ).toEqual(['Colin 72%']);
    expect(view().textContent).toBe(TEXT);
    expect(document.getElementById('ingredients-text-tools').hidden).toBe(
      false,
    );
    expect(document.getElementById('ingredients-text-legend').hidden).toBe(
      false,
    );
  });

  it('does nothing on a page that has no text', () => {
    document.body.innerHTML = '<form id="product-form"></form>';

    expect(() => initIngredientsText()).not.toThrow();
  });

  it('can act only when a part of the text is selected', () => {
    page();
    initIngredientsText();
    expect(button('ignore').disabled).toBe(true);
    expect(button('restore').disabled).toBe(true);

    selectText(ZONE[0], ZONE[1]);

    expect(button('ignore').disabled).toBe(false);
    expect(button('restore').disabled).toBe(false);
  });

  it('reads the text again without the part that was selected', async () => {
    page();
    const onRead = vi.fn();
    initIngredientsText({ onRead });
    fetch.mockResolvedValue({
      ok: true,
      json: async () =>
        reading([
          [0, 9],
          [37, 40],
        ]),
    });

    selectText(ZONE[0], ZONE[1]);
    button('ignore').click();
    await vi.waitFor(() => expect(onRead).toHaveBeenCalled());

    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe('/products/read-label/');
    expect(options.method).toBe('POST');
    expect(options.headers['X-CSRFToken']).toBe('token-1');
    expect(JSON.parse(options.body)).toEqual({
      text: TEXT,
      language: 'fr',
      ignored: [ZONE],
    });
    expect(onRead.mock.calls[0][0].rows).toEqual([{ name: 'colin' }]);
    expect(view().querySelector('s').textContent).toBe(TEXT.slice(...ZONE));
    expect(button('clear').hidden).toBe(false);
  });

  it('keeps in the form what it takes to save the new reading', async () => {
    page();
    const onRead = vi.fn();
    initIngredientsText({ onRead });

    selectText(ZONE[0], ZONE[1]);
    button('ignore').click();
    await vi.waitFor(() => expect(onRead).toHaveBeenCalled());

    expect(hidden('off_ingredients')).toBe('[{"name":"colin"}]');
    expect(hidden('off_ingredients_text')).toBe(TEXT);
    expect(hidden('off_barcode')).toBe('3017620422003');
    expect(JSON.parse(hidden('ingredients_ignored'))).toEqual([ZONE]);
  });

  it('does not take over the barcode of a page that came from a lookup', async () => {
    page();
    document.querySelector('[name="off_barcode"]').value = '3229820794556';
    const onRead = vi.fn();
    initIngredientsText({ onRead });

    selectText(0, 5);
    button('ignore').click();
    await vi.waitFor(() => expect(onRead).toHaveBeenCalled());

    expect(hidden('off_barcode')).toBe('3229820794556');
  });

  it('puts a selected part back, and everything back', async () => {
    page({ ignored: [ZONE], used: [[0, 9]] });
    const onRead = vi.fn();
    initIngredientsText({ onRead });
    expect(button('clear').hidden).toBe(false);

    selectText(ZONE[0], ZONE[0] + 5);
    button('restore').click();
    await vi.waitFor(() => expect(onRead).toHaveBeenCalledTimes(1));
    expect(JSON.parse(fetch.mock.calls[0][1].body).ignored).toEqual([
      [ZONE[0] + 5, ZONE[1]],
    ]);

    button('clear').click();
    await vi.waitFor(() => expect(onRead).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetch.mock.calls[1][1].body).ignored).toEqual([]);
    expect(button('clear').hidden).toBe(true);
    expect(hidden('ingredients_ignored')).toBe('[]');
  });

  it('leaves the white space of the selection out of the place', async () => {
    page();
    const onRead = vi.fn();
    initIngredientsText({ onRead });

    selectText(5, 18);
    button('ignore').click();
    await vi.waitFor(() => expect(onRead).toHaveBeenCalled());

    const [start, end] = JSON.parse(fetch.mock.calls[0][1].body).ignored[0];
    expect(TEXT.slice(start, end)).toBe(TEXT.slice(start, end).trim());
  });

  it('says what looks wrong in the text, and what stopped the reading', async () => {
    page();
    const onRead = vi.fn();
    initIngredientsText({ onRead });
    fetch.mockResolvedValue({
      ok: true,
      json: async () =>
        reading(
          [],
          [
            { message: 'Parentheses do not match.', stops: true },
            { message: 'More than 100.', stops: false },
          ],
        ),
    });

    selectText(0, 5);
    button('ignore').click();
    await vi.waitFor(() => expect(onRead).toHaveBeenCalled());

    const lines = [
      ...document.getElementById('ingredients-text-warnings').children,
    ];
    expect(lines.map((line) => line.textContent)).toEqual([
      'Parentheses do not match.',
      'More than 100.',
    ]);
    expect(lines[0].className).toContain('text-danger');
    expect(lines[1].className).not.toContain('text-danger');
    expect(view().querySelector('mark')).toBeNull();
  });

  it('says so when the text could not be read again, and changes nothing', async () => {
    page();
    const onRead = vi.fn();
    initIngredientsText({ onRead });
    fetch.mockResolvedValue({ ok: false, status: 500, json: async () => ({}) });

    selectText(0, 5);
    button('ignore').click();
    await vi.waitFor(() =>
      expect(
        document.getElementById('ingredients-text-status').textContent,
      ).toBe('Failed.'),
    );

    expect(onRead).not.toHaveBeenCalled();
    expect(view().querySelector('s')).toBeNull();
    expect(hidden('ingredients_ignored')).toBe('[]');
    expect(button('clear').hidden).toBe(true);
  });

  it('keeps the buttons off while it reads', async () => {
    page();
    let finish;
    fetch.mockReturnValue(
      new Promise((resolve) => {
        finish = () => resolve({ ok: true, json: async () => reading([]) });
      }),
    );
    initIngredientsText();

    selectText(0, 5);
    button('ignore').click();

    expect(button('ignore').disabled).toBe(true);
    expect(document.getElementById('ingredients-text-status').textContent).toBe(
      'Reading…',
    );
    finish();
    await vi.waitFor(() =>
      expect(
        document.getElementById('ingredients-text-status').textContent,
      ).toBe(''),
    );
  });
});
