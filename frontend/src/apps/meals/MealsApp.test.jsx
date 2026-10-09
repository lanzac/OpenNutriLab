import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { MealsApp } from './MealsApp.jsx';

// Stands in for the |json_script blob rendered by MealsView: the real French
// catalogue entries, so a regression back to hardcoded English fails these.
const labels = {
  loading: 'Chargement…',
  loadError: 'Les repas n’ont pas pu être chargés.',
  saveError: 'Le changement n’a pas pu être enregistré.',
  previousDay: 'Jour précédent',
  nextDay: 'Jour suivant',
  day: 'Jour',
  today: 'Aujourd’hui',
  emptyInventory: 'Votre inventaire est vide.',
  goInventory: 'Aller à l’inventaire',
  serving: 'portion',
  quantity: 'Quantité',
  unit: 'Unité',
  noMass: 'pas de portion',
  remove: 'Retirer du repas',
  addProduct: 'Ajouter un produit',
  chooseProduct: 'Choisir un produit…',
  add: 'Ajouter',
  emptyMeal: 'Rien dans ce repas.',
  noProfile: 'Renseignez votre profil.',
  myNeeds: 'Mes besoins',
  emptyDay: 'Mettez des produits dans un repas.',
  dayTitle: 'La journée face à vos besoins',
  coverageNote:
    'Couverture : la part des aliments dont la composition donne une valeur.',
  nutrient: 'Nutriment',
  total: 'Total',
  need: 'Besoin',
  status: 'Statut',
  coverage: 'Couverture',
  ratios: 'Rapports',
  ratio: 'Rapport',
  inMoles: 'en moles',
  below: 'Sous',
  within: 'Atteint',
  above: 'Au-dessus',
  unknown: 'Inconnu',
  uncertain: 'Pas certain',
};

const BREAD = {
  barcode: '3228857002245',
  name: 'Pain de mie',
  serving: { quantity: '35.70', unit: 'g', name: '1 tranche' },
  added_at: '2026-10-09T10:00:00Z',
};
const MUESLI = {
  barcode: '3229820794556',
  name: 'Muesli',
  serving: null,
  added_at: '2026-10-09T10:00:00Z',
};

const total = (amount, low = amount, high = amount, coverage = '100') => ({
  amount,
  low,
  high,
  coverage,
});

function meal(kind, label, items = [], totals = {}) {
  return { kind, label, items, mass: '0', totals };
}

function day(overrides = {}) {
  return {
    day: '2026-10-09',
    meals: [
      meal('breakfast', 'Petit-déjeuner'),
      meal('lunch', 'Déjeuner'),
      meal('snack', 'Collation'),
      meal('dinner', 'Dîner'),
    ],
    mass: '0',
    totals: {},
    nutrients: {},
    needs: null,
    ratios: null,
    ...overrides,
  };
}

const breadItem = {
  id: 7,
  barcode: BREAD.barcode,
  name: BREAD.name,
  quantity: '2.00',
  unit: 'serving',
  grams: '71.40',
  serving: BREAD.serving,
};

const withBread = (extra = {}) =>
  day({
    mass: '71.4',
    meals: [
      meal('breakfast', 'Petit-déjeuner', [breadItem], {
        energy: total('3766.68', '3700', '3800'),
        proteins: total('7.854', '7.5', '8.2'),
      }),
      meal('lunch', 'Déjeuner'),
      meal('snack', 'Collation'),
      meal('dinner', 'Dîner'),
    ],
    totals: { energy: total('3766.68', '3700', '3800') },
    nutrients: {
      energy: { name: 'Énergie', unit: 'kJ' },
      proteins: { name: 'Protéines', unit: 'g' },
    },
    ...extra,
  });

const ok = (body) => ({ ok: true, json: async () => body });

/** fetch, answering by method and URL; records what was asked. */
function stubFetch(routes) {
  const fetch = vi.fn(async (url, options = {}) => {
    const key = `${options.method ?? 'GET'} ${url}`;
    const answer = routes[key];
    if (!answer) throw new Error(`unexpected request: ${key}`);
    return typeof answer === 'function' ? answer(options) : answer;
  });
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

const TODAY = '2026-10-09';
const DAY_URL = `/api/v1/meals/${TODAY}`;

function renderApp() {
  return render(
    <MealsApp
      labels={labels}
      csrfToken="test-csrf-token"
      languageCode="fr-fr"
      today={TODAY}
      needsUrl="/needs/"
      inventoryUrl="/products/"
    />,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('MealsApp', () => {
  it('shows the four meals of the day, in the language served', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day({ needs: [], ratios: [] })),
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    renderApp();

    for (const label of ['Petit-déjeuner', 'Déjeuner', 'Collation', 'Dîner']) {
      expect(
        await screen.findByRole('region', { name: label }),
      ).toBeInTheDocument();
    }
    expect(screen.getAllByText('Rien dans ce repas.')).toHaveLength(4);
    expect(
      screen.getByText('Mettez des produits dans un repas.'),
    ).toBeInTheDocument();
  });

  it('shows what a meal holds and what it brings, the energy in kcal', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withBread()),
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    renderApp();

    const breakfast = await screen.findByRole('region', {
      name: 'Petit-déjeuner',
    });
    expect(within(breakfast).getByText('Pain de mie')).toBeInTheDocument();
    expect(
      within(breakfast).getByLabelText('Quantité – Pain de mie'),
    ).toHaveValue(2);
    expect(within(breakfast).getByText('71,4 g')).toBeInTheDocument();
    // 3766.68 kJ is 900 kcal.
    expect(within(breakfast).getByText('900 kcal')).toBeInTheDocument();
    expect(within(breakfast).getByText('7,85 g')).toBeInTheDocument();
    // The interval and the coverage are on the figure.
    expect(within(breakfast).getByText('900 kcal')).toHaveAttribute(
      'title',
      expect.stringContaining('884 – 908'),
    );
  });

  it('puts a product in a meal with the CSRF token, and shows the day it answers with', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
      [`POST ${DAY_URL}/breakfast/items`]: ok(withBread()),
    });
    renderApp();
    const breakfast = await screen.findByRole('region', {
      name: 'Petit-déjeuner',
    });

    fireEvent.change(
      within(breakfast).getByLabelText('Ajouter un produit – Petit-déjeuner'),
      { target: { value: BREAD.barcode } },
    );
    // A product with a serving is counted in servings, one serving to begin with.
    expect(
      within(breakfast).getByLabelText('Unité – Petit-déjeuner'),
    ).toHaveValue('serving');
    fireEvent.change(
      within(breakfast).getByLabelText('Quantité – Petit-déjeuner'),
      {
        target: { value: '2' },
      },
    );
    fireEvent.click(within(breakfast).getByRole('button', { name: 'Ajouter' }));

    // The row of the item: the name is also an option of the lists.
    expect(
      await within(breakfast).findByLabelText('Quantité – Pain de mie'),
    ).toBeInTheDocument();
    const [, options] = fetch.mock.calls.find(([, o]) => o?.method === 'POST');
    expect(JSON.parse(options.body)).toEqual({
      barcode: BREAD.barcode,
      quantity: 2,
      unit: 'serving',
    });
    expect(options.headers['X-CSRFToken']).toBe('test-csrf-token');
  });

  it('counts a product with no serving in grams', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([MUESLI]),
    });
    renderApp();
    const lunch = await screen.findByRole('region', { name: 'Déjeuner' });

    fireEvent.change(
      within(lunch).getByLabelText('Ajouter un produit – Déjeuner'),
      {
        target: { value: MUESLI.barcode },
      },
    );

    expect(within(lunch).getByLabelText('Unité – Déjeuner')).toHaveValue('g');
    expect(within(lunch).getByLabelText('Quantité – Déjeuner')).toHaveValue(
      100,
    );
    // No serving to choose.
    expect(within(lunch).queryByRole('option', { name: /portion/ })).toBeNull();
  });

  it('does not offer a product already in the meal', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withBread()),
      'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
    });
    renderApp();
    const breakfast = await screen.findByRole('region', {
      name: 'Petit-déjeuner',
    });
    const lunch = screen.getByRole('region', { name: 'Déjeuner' });

    const offered = (card, name) =>
      within(within(card).getByLabelText(name))
        .getAllByRole('option')
        .map((o) => o.textContent);
    expect(offered(breakfast, 'Ajouter un produit – Petit-déjeuner')).toEqual([
      'Choisir un produit…',
      'Muesli',
    ]);
    expect(offered(lunch, 'Ajouter un produit – Déjeuner')).toEqual([
      'Choisir un produit…',
      'Pain de mie',
      'Muesli',
    ]);
  });

  it('changes a quantity when the field is left, and not when it did not change', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(withBread()),
      'GET /api/v1/inventory/': ok([BREAD]),
      'PATCH /api/v1/meals/items/7': ok(withBread()),
    });
    renderApp();
    const field = await screen.findByLabelText('Quantité – Pain de mie');

    fireEvent.blur(field);
    expect(fetch.mock.calls.some(([, o]) => o?.method === 'PATCH')).toBe(false);

    fireEvent.change(field, { target: { value: '3' } });
    fireEvent.blur(field);

    await waitFor(() =>
      expect(fetch.mock.calls.some(([, o]) => o?.method === 'PATCH')).toBe(
        true,
      ),
    );
    const [, options] = fetch.mock.calls.find(([, o]) => o?.method === 'PATCH');
    expect(JSON.parse(options.body)).toEqual({ quantity: 3, unit: 'serving' });
    expect(options.headers['X-CSRFToken']).toBe('test-csrf-token');
  });

  it('changes the unit at once, keeping the quantity', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(withBread()),
      'GET /api/v1/inventory/': ok([BREAD]),
      'PATCH /api/v1/meals/items/7': ok(withBread()),
    });
    renderApp();

    fireEvent.change(await screen.findByLabelText('Unité – Pain de mie'), {
      target: { value: 'g' },
    });

    await waitFor(() =>
      expect(fetch.mock.calls.some(([, o]) => o?.method === 'PATCH')).toBe(
        true,
      ),
    );
    const [, options] = fetch.mock.calls.find(([, o]) => o?.method === 'PATCH');
    expect(JSON.parse(options.body)).toEqual({ quantity: 2, unit: 'g' });
  });

  it('takes a product out of a meal', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(withBread()),
      'GET /api/v1/inventory/': ok([BREAD]),
      'DELETE /api/v1/meals/items/7': ok(day()),
    });
    renderApp();

    fireEvent.click(
      await screen.findByRole('button', {
        name: 'Retirer du repas – Pain de mie',
      }),
    );

    await waitFor(() =>
      expect(screen.queryByLabelText('Quantité – Pain de mie')).toBeNull(),
    );
    expect(fetch).toHaveBeenLastCalledWith(
      '/api/v1/meals/items/7',
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('moves from day to day', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/meals/2026-10-10': ok(day({ day: '2026-10-10' })),
      'GET /api/v1/meals/2026-10-08': ok(day({ day: '2026-10-08' })),
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    renderApp();
    await screen.findByRole('region', { name: 'Déjeuner' });
    const today = screen.getByRole('button', { name: 'Aujourd’hui' });
    expect(today).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Jour suivant' }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        '/api/v1/meals/2026-10-10',
        expect.anything(),
      ),
    );
    expect(await screen.findByLabelText('Jour')).toHaveValue('2026-10-10');
    expect(today).toBeEnabled();

    fireEvent.click(today);
    await waitFor(() =>
      expect(screen.getByLabelText('Jour')).toHaveValue(TODAY),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Jour précédent' }));
    await waitFor(() =>
      expect(screen.getByLabelText('Jour')).toHaveValue('2026-10-08'),
    );
  });

  it('shows an answer for the day asked for only', async () => {
    let answerFirst;
    stubFetch({
      [`GET ${DAY_URL}`]: () =>
        new Promise((resolve) => {
          answerFirst = resolve;
        }),
      'GET /api/v1/meals/2026-10-10': ok(day({ day: '2026-10-10', mass: '0' })),
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    renderApp();
    await screen.findByLabelText('Jour');

    fireEvent.click(screen.getByRole('button', { name: 'Jour suivant' }));
    await screen.findByRole('region', { name: 'Déjeuner' });
    answerFirst(ok(withBread()));

    // The late answer for the first day does not replace the second.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByLabelText('Quantité – Pain de mie')).toBeNull();
  });

  it('says the profile is missing when there are no needs to set the day against', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withBread()),
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    renderApp();

    expect(
      await screen.findByText(/Renseignez votre profil/),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Mes besoins' })).toHaveAttribute(
      'href',
      '/needs/',
    );
  });

  it('says there is nothing to put in a meal when the inventory is empty', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([]),
    });
    renderApp();

    expect(
      await screen.findByText(/Votre inventaire est vide/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Aller à l’inventaire' }),
    ).toHaveAttribute('href', '/products/');
  });

  it('shows a translated error when the day cannot be loaded, and when a change fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    stubFetch({
      [`GET ${DAY_URL}`]: { ok: false, status: 500 },
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    renderApp();

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Les repas n’ont pas pu être chargés.',
    );
  });

  it('says so when a change cannot be saved, and keeps the day shown', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withBread()),
      'GET /api/v1/inventory/': ok([BREAD]),
      'DELETE /api/v1/meals/items/7': { ok: false, status: 403 },
    });
    renderApp();

    fireEvent.click(
      await screen.findByRole('button', {
        name: 'Retirer du repas – Pain de mie',
      }),
    );

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Le changement n’a pas pu être enregistré.',
    );
    expect(screen.getByLabelText('Quantité – Pain de mie')).toBeInTheDocument();
  });
});

describe('the day against the needs', () => {
  const need = (overrides) => ({
    name: 'Fibres',
    unit: 'g',
    group: 'macronutrient',
    group_label: 'Macronutriment',
    low: '30',
    high: null,
    ends: ['Borne de l’optimisation (anses-2016)'],
    share_low: null,
    share_high: null,
    total: total('12', '10', '14', '100'),
    status: 'below',
    certain: true,
    ...overrides,
  });

  const ratio = (overrides) => ({
    numerator: 'Oméga-3',
    denominator: 'Oméga-6',
    molar: false,
    low: '0.9',
    high: '1.1',
    end: 'Votre objectif (user)',
    value: '0.23',
    value_low: '0.2',
    value_high: null,
    status: 'below',
    certain: false,
    ...overrides,
  });

  const withNeeds = () =>
    withBread({
      needs: [
        need({}),
        need({
          name: 'Énergie',
          unit: 'kJ',
          group: 'energy',
          group_label: 'Énergie',
          low: '10536',
          high: '11645',
          total: total('3766.68', '3700', '3800', '100'),
        }),
        need({
          name: 'Sodium',
          unit: 'mg',
          group: 'mineral',
          group_label: 'Minéral',
          low: '1500',
          high: '2300',
          total: total('1800', '1500', null, '60'),
          status: 'within',
          certain: false,
        }),
      ],
      ratios: [
        ratio({}),
        ratio({
          numerator: 'Sodium',
          molar: true,
          value: null,
          value_low: null,
          status: 'unknown',
        }),
      ],
    });

  it('sets each total against its need, with its range and coverage', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withNeeds()),
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    renderApp();

    const summary = await screen.findByRole('region', {
      name: 'La journée face à vos besoins',
    });
    const fibre = within(summary).getByRole('row', { name: /Fibres/ });
    expect(within(fibre).getByText('12 g')).toBeInTheDocument();
    expect(within(fibre).getByText('10 – 14')).toBeInTheDocument();
    expect(within(fibre).getByText('≥ 30 g')).toBeInTheDocument();
    expect(within(fibre).getByText('Sous')).toBeInTheDocument();
    // The energy is in kcal here too: 3766.68 kJ is 900, and 10536 kJ is 2518.
    const energy = within(summary).getByRole('row', { name: /Énergie 9/ });
    expect(within(energy).getByText('≥ 2 518 kcal')).toBeInTheDocument();
    expect(within(energy).getByText('≤ 2 783 kcal')).toBeInTheDocument();
    // Grouped as the catalogue is.
    expect(within(summary).getByText('Macronutriment')).toBeInTheDocument();
    expect(within(summary).getByText('Minéral')).toBeInTheDocument();
  });

  it('says a verdict is not certain, and a nutrient is not covered', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withNeeds()),
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    renderApp();

    const summary = await screen.findByRole('region', {
      name: 'La journée face à vos besoins',
    });
    const sodium = within(summary).getByRole('row', { name: /Sodium 1/ });
    const badge = within(sodium).getByText('Atteint ?');
    expect(badge).toHaveAttribute('title', 'Pas certain');
    expect(
      within(sodium).getByText('1 800 mg').closest('td'),
    ).toHaveTextContent('1 500 – ?');
    expect(within(sodium).getByText('60 %')).toHaveClass(
      'text-warning-emphasis',
    );
    // A certain verdict has no question mark.
    expect(
      within(within(summary).getByRole('row', { name: /Fibres/ })).getByText(
        'Sous',
      ),
    ).not.toHaveAttribute('title');
  });

  it('sets the ratios against their ends, and a ratio over nothing is unknown', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withNeeds()),
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    renderApp();

    const summary = await screen.findByRole('region', {
      name: 'La journée face à vos besoins',
    });
    const omega = within(summary).getByRole('row', { name: /Oméga-3/ });
    expect(within(omega).getByText('0,23')).toBeInTheDocument();
    expect(within(omega).getByText('≥ 0,9')).toBeInTheDocument();
    expect(within(omega).getByText('≤ 1,1')).toBeInTheDocument();
    const sodium = within(summary).getByRole('row', {
      name: /Sodium \/ Oméga-6/,
    });
    expect(within(sodium).getByText('Inconnu ?')).toBeInTheDocument();
    expect(
      within(sodium).getByText('en moles', { exact: false }),
    ).toBeInTheDocument();
  });
});
