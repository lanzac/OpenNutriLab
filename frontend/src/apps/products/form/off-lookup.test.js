import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fieldChanges, initOffLookup, sameValue } from './off-lookup.js';

const LABELS = {
  enterBarcode: 'Enter a barcode.',
  asking: 'Asking…',
  failed: 'Unreachable.',
  taken: 'Taken: %(count)s.',
  same: 'Same.',
  title: 'Choose.',
  inForm: 'In the form',
  onOff: 'On OFF',
  nothing: '(nothing)',
  selectAll: 'Select all',
  apply: 'Take',
  cancel: 'Keep',
  ingredientList: 'Ingredient list',
  photo: 'Photo',
  groups: 'Group',
  subgroups: 'Sub-group',
};
const CONFIG = { url: '/products/lookup-off/', labels: LABELS };

const LABEL = {
  barcode: '3017620422003',
  text: 'Sucre, huile.',
  language: 'fr',
  ingredients: '[{"name":"sucre"}]',
  rows: [{ name: 'sucre' }],
  used: [[0, 12]],
};

const ANSWER = {
  fields: {
    barcode: '3017620422003',
    name: 'Pâte à tartiner',
    nutrient_energy: '2252.00',
    nutrition_unit: 'ml',
    group_level_1: 'Sugary snacks',
    group_level_2: '',
  },
  image: 'https://images.openfoodfacts.org/new.jpg',
  label: LABEL,
  notices: [],
};

/** The form as the page draws it, for a new product or a saved one. */
function page({
  saved = false,
  name = '',
  energy = '',
  group = 'Unknown',
  photo = false,
} = {}) {
  document.body.innerHTML = `
    <form id="product-form">
      <input type="hidden" name="off_barcode" value="">
      <input type="hidden" name="off_image_url" value="">
      <input type="text" id="id_barcode" name="barcode" value="3017620422003" ${saved ? 'disabled' : ''}>
      <button type="button" id="off-lookup">Load</button>
      <div id="off-lookup-status"></div>
      <div id="off-review" hidden></div>
      <img class="product-image-preview" src="/static/milk.png" ${photo ? '' : 'data-placeholder="1"'}>
      <label for="id_name">Name *</label>
      <input type="text" id="id_name" name="name" value="${name}">
      <input type="hidden" name="group_level_1" value="${group}">
      <input type="hidden" name="group_level_2" value="${group}">
      <label for="id_nutrient_energy">Energy</label>
      <div class="input-group">
        <input type="number" id="id_nutrient_energy" name="nutrient_energy" value="${energy}">
        <span class="input-group-text">kJ</span>
      </div>
      <select id="id_nutrition_unit" name="nutrition_unit">
        <option value="g" selected>100 g</option>
        <option value="ml">100 ml</option>
      </select>
      <input type="number" name="serving_quantity" value="">
      <select name="serving_unit">
        <option value="g" selected>g</option>
        <option value="ml">ml</option>
      </select>
    </form>`;
}

const $ = (id) => document.getElementById(id);
const value = (name) => document.querySelector(`[name="${name}"]`).value;
const status = () => $('off-lookup-status').textContent;
const review = () => $('off-review');
const boxes = () => [
  ...review().querySelectorAll('tbody input[type="checkbox"]'),
];
const captions = () =>
  [...review().querySelectorAll('tbody tr')].map(
    (row) => row.cells[1].textContent,
  );

function answers(body, ok = true) {
  return vi
    .fn()
    .mockResolvedValue({ ok, status: ok ? 200 : 404, json: async () => body });
}

function ingredientsList(text = '') {
  return { text: vi.fn(() => text), load: vi.fn() };
}

describe('sameValue', () => {
  it('counts figures by what they are worth', () => {
    expect(sameValue('12.50', '12.5', true)).toBe(true);
    expect(sameValue('12,5', '12.5', true)).toBe(true);
    expect(sameValue('12.5', '13', true)).toBe(false);
  });

  it('counts anything else as written, but for the white space around it', () => {
    expect(sameValue(' Colin ', 'Colin')).toBe(true);
    expect(sameValue('1', '1.0')).toBe(false);
    expect(sameValue('', '0', true)).toBe(false);
  });
});

describe('fieldChanges', () => {
  it('lists what differs, with the captions of the form and its units', () => {
    page({ name: 'Old name', energy: '100' });

    const changes = fieldChanges(
      $('product-form'),
      { name: 'New name', nutrient_energy: '2252.00' },
      {},
    );

    expect(
      changes.map((c) => [c.label, c.current, c.proposed, c.fills]),
    ).toEqual([
      ['Name', 'Old name', 'New name', false],
      ['Energy', '100 kJ', '2252.00 kJ', false],
    ]);
  });

  it('leaves out what is the same, and what OpenFoodFacts does not have', () => {
    page({ name: 'Same', energy: '2252' });

    const changes = fieldChanges(
      $('product-form'),
      {
        name: 'Same',
        nutrient_energy: '2252.00',
        description: '',
        unknown_field: 'x',
      },
      {},
    );

    expect(changes).toEqual([]);
  });

  it('does not offer the barcode of a saved product, nor a field it cannot change', () => {
    page({ saved: true });

    expect(
      fieldChanges($('product-form'), { barcode: '0000000000000' }, {}),
    ).toEqual([]);
  });

  it('shows a choice by its caption', () => {
    page();

    const [change] = fieldChanges(
      $('product-form'),
      { nutrition_unit: 'ml' },
      {},
    );

    expect(change.proposed).toBe('100 ml');
  });

  it('shows the food group a product has none of as nothing', () => {
    page({ saved: true });

    const [change] = fieldChanges(
      $('product-form'),
      { group_level_1: 'Snacks' },
      {},
    );

    expect(change.current).toBe('');
  });

  it('counts as filling a field that is empty, or still has what a new page starts with', () => {
    page();

    const changes = fieldChanges(
      $('product-form'),
      {
        name: 'A',
        nutrition_unit: 'ml',
        group_level_1: 'Snacks',
        serving_unit: 'ml',
      },
      { group_level_1: 'Group' },
    );

    expect(changes.map((c) => c.fills)).toEqual([true, true, true, true]);
  });

  it('counts a saved product’s unit as replaced, but not the unit of a serving it has none of', () => {
    page({ saved: true, name: 'Saved' });

    const changes = fieldChanges(
      $('product-form'),
      { nutrition_unit: 'ml', serving_unit: 'ml' },
      {},
    );

    expect(changes.map((c) => [c.label, c.fills])).toEqual([
      ['nutrition_unit', false],
      ['serving_unit', true],
    ]);
  });

  it('writes a value the way a person would, so that what listens to the field hears it', () => {
    page();
    const heard = vi.fn();
    $('id_nutrient_energy').addEventListener('input', heard);

    fieldChanges($('product-form'), { nutrient_energy: '99' }, {})[0].apply();

    expect(value('nutrient_energy')).toBe('99');
    expect(heard).toHaveBeenCalled();
  });
});

describe('initOffLookup', () => {
  beforeEach(() => {
    vi.spyOn(window, 'alert').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('asks for the barcode of the form, and does not reload the page', async () => {
    page();
    const fetch = answers(ANSWER);
    vi.stubGlobal('fetch', fetch);
    initOffLookup(CONFIG, ingredientsList());

    $('off-lookup').click();
    await vi.waitFor(() => expect(status()).toContain('Taken'));

    expect(fetch.mock.calls[0][0]).toBe(
      '/products/lookup-off/?barcode=3017620422003',
    );
  });

  it('asks for a barcode when there is none', async () => {
    page();
    $('id_barcode').value = ' ';
    const fetch = answers(ANSWER);
    vi.stubGlobal('fetch', fetch);
    initOffLookup(CONFIG, ingredientsList());

    $('off-lookup').click();

    expect(window.alert).toHaveBeenCalledWith('Enter a barcode.');
    expect(fetch).not.toHaveBeenCalled();
  });

  it('fills a form that has nothing yet without asking, and says how much it took', async () => {
    page();
    const list = ingredientsList();
    vi.stubGlobal('fetch', answers(ANSWER));
    initOffLookup(CONFIG, list);

    $('off-lookup').click();
    await vi.waitFor(() => expect(status()).toContain('Taken'));

    expect(review().hidden).toBe(true);
    expect(value('name')).toBe('Pâte à tartiner');
    expect(value('nutrient_energy')).toBe('2252.00');
    expect(value('nutrition_unit')).toBe('ml');
    // The list, the photo, and the fields: all of it filled in.
    expect(list.load).toHaveBeenCalledWith({ ...LABEL, text: 'Sucre, huile.' });
    expect(value('off_image_url')).toBe(
      'https://images.openfoodfacts.org/new.jpg',
    );
    expect(value('off_barcode')).toBe('3017620422003');
    expect($('product-form').querySelector('img').src).toBe(
      'https://images.openfoodfacts.org/new.jpg',
    );
    expect(status()).toBe('Taken: 6.');
  });

  it('shows the two values side by side when the form has others, and changes nothing yet', async () => {
    page({ saved: true, name: 'My name', energy: '100' });
    const list = ingredientsList('Old list');
    vi.stubGlobal('fetch', answers(ANSWER));
    initOffLookup(CONFIG, list);

    $('off-lookup').click();
    await vi.waitFor(() => expect(review().hidden).toBe(false));

    expect(captions()).toEqual([
      'Name',
      'Energy',
      'nutrition_unit',
      'Group',
      'Ingredient list',
      'Photo',
    ]);
    const nameRow = review().querySelector('tbody tr');
    expect(nameRow.cells[2].textContent).toBe('My name');
    expect(nameRow.cells[3].textContent).toBe('Pâte à tartiner');
    expect(value('name')).toBe('My name');
    expect(value('nutrient_energy')).toBe('100');
    expect(list.load).not.toHaveBeenCalled();
  });

  it('takes only what is ticked', async () => {
    page({ saved: true, name: 'My name', energy: '100', photo: true });
    const list = ingredientsList('Old list');
    vi.stubGlobal('fetch', answers(ANSWER));
    initOffLookup(CONFIG, list);
    $('off-lookup').click();
    await vi.waitFor(() => expect(review().hidden).toBe(false));

    // Keep my name; take the rest, but not the photo, which is not ticked by itself.
    boxes()[0].checked = false;
    expect(boxes().at(-1).checked).toBe(false);
    review().querySelector('.btn-primary').click();

    expect(value('name')).toBe('My name');
    expect(value('nutrient_energy')).toBe('2252.00');
    expect(list.load).toHaveBeenCalledTimes(1);
    expect(value('off_image_url')).toBe('');
    expect(review().hidden).toBe(true);
    expect(status()).toBe('Taken: 4.');
  });

  it('ticks the photo by itself only when the product has none', async () => {
    page({ saved: true, name: 'My name' });
    vi.stubGlobal('fetch', answers(ANSWER));
    initOffLookup(CONFIG, ingredientsList('Old list'));
    $('off-lookup').click();
    await vi.waitFor(() => expect(review().hidden).toBe(false));

    expect(boxes().at(-1).checked).toBe(true);
  });

  it('keeps the barcode of a saved product, whatever OpenFoodFacts spells it as', async () => {
    page({ saved: true, name: 'My name' });
    const list = ingredientsList('Old list');
    vi.stubGlobal(
      'fetch',
      answers({
        ...ANSWER,
        fields: { ...ANSWER.fields, barcode: '0003017620422003' },
      }),
    );
    initOffLookup(CONFIG, list);
    $('off-lookup').click();
    await vi.waitFor(() => expect(review().hidden).toBe(false));

    review().querySelector('.btn-primary').click();

    expect(value('barcode')).toBe('3017620422003');
    expect(list.load.mock.calls[0][0].barcode).toBe('3017620422003');
  });

  it('changes nothing when the person keeps the form', async () => {
    page({ saved: true, name: 'My name' });
    vi.stubGlobal('fetch', answers(ANSWER));
    initOffLookup(CONFIG, ingredientsList('Old list'));
    $('off-lookup').click();
    await vi.waitFor(() => expect(review().hidden).toBe(false));

    review().querySelector('.btn-outline-secondary').click();

    expect(review().hidden).toBe(true);
    expect(value('name')).toBe('My name');
    expect(status()).toBe('');
  });

  it('says so when the form has what OpenFoodFacts has', async () => {
    page({ name: 'Pâte à tartiner', energy: '2252', group: 'Sugary snacks' });
    $('product-form').querySelector('select[name="nutrition_unit"]').value =
      'ml';
    const list = ingredientsList('Sucre, huile.');
    vi.stubGlobal(
      'fetch',
      answers({
        ...ANSWER,
        image: null,
        fields: { ...ANSWER.fields, group_level_2: '' },
      }),
    );
    document.querySelector('[name="group_level_2"]').value = 'x';
    initOffLookup(CONFIG, list);

    $('off-lookup').click();
    await vi.waitFor(() => expect(status()).toBe('Same.'));

    expect(review().hidden).toBe(true);
  });

  it('tells what OpenFoodFacts could not give, and leaves the form alone', async () => {
    page({ name: 'Mine' });
    vi.stubGlobal('fetch', answers({ error: 'Not found.' }, false));
    initOffLookup(CONFIG, ingredientsList());

    $('off-lookup').click();
    await vi.waitFor(() => expect(status()).toBe('Not found.'));

    expect(value('name')).toBe('Mine');
    expect($('off-lookup').disabled).toBe(false);
  });

  it('tells the notices a lookup comes with', async () => {
    page();
    vi.stubGlobal(
      'fetch',
      answers({ ...ANSWER, notices: ['The quantity could not be read.'] }),
    );
    initOffLookup(CONFIG, ingredientsList());

    $('off-lookup').click();
    await vi.waitFor(() =>
      expect(status()).toContain('The quantity could not be read.'),
    );
  });

  it('looks up the barcode of a product chosen in a search, and puts it in the form', async () => {
    page();
    $('id_barcode').value = '';
    const fetch = answers(ANSWER);
    vi.stubGlobal('fetch', fetch);
    const lookup = initOffLookup(CONFIG, ingredientsList());

    await lookup.lookup('3700966568466');

    expect(fetch.mock.calls[0][0]).toBe(
      '/products/lookup-off/?barcode=3700966568466',
    );
  });
});
