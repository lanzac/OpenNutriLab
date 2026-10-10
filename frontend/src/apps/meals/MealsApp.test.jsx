import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  BREAD,
  COMPOTE,
  DAY_URL,
  MUESLI,
  day,
  labels,
  meal,
  need,
  ok,
  ratio,
  renderApp,
  stubFetch,
  total,
  withBread,
} from './fixtures.jsx';

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
    // Each with what its package holds.
    expect(offered(breakfast, 'Ajouter un produit – Petit-déjeuner')).toEqual([
      'Choisir un produit…',
      'Muesli (375 g)',
    ]);
    expect(offered(lunch, 'Ajouter un produit – Déjeuner')).toEqual([
      'Choisir un produit…',
      'Pain de mie (500 g)',
      'Muesli (375 g)',
    ]);
  });

  it("names a product's serving as its label does, in a meal and when adding", async () => {
    const unnamed = {
      ...MUESLI,
      barcode: '3229820794557',
      name: 'Barre',
      serving: { quantity: '30.00', unit: 'g', name: '' },
    };
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withBread()),
      'GET /api/v1/inventory/': ok([BREAD, COMPOTE, unnamed]),
    });
    renderApp();
    const breakfast = await screen.findByRole('region', {
      name: 'Petit-déjeuner',
    });
    const lunch = screen.getByRole('region', { name: 'Déjeuner' });
    const unitsOf = (card, label) =>
      within(within(card).getByLabelText(label))
        .getAllByRole('option')
        .map((o) => o.textContent);

    // The item of the meal: the name of the label, with what it weighs.
    expect(unitsOf(breakfast, 'Unité – Pain de mie')).toEqual([
      '1 tranche (35,7 g)',
      'g',
    ]);

    // The product being added, named or not.
    const choose = (barcode) =>
      fireEvent.change(
        within(lunch).getByLabelText('Ajouter un produit – Déjeuner'),
        { target: { value: barcode } },
      );
    choose(COMPOTE.barcode);
    expect(unitsOf(lunch, 'Unité – Déjeuner')).toEqual(['1 pot (100 g)', 'g']);
    choose(unnamed.barcode);
    expect(unitsOf(lunch, 'Unité – Déjeuner')).toEqual(['portion (30 g)', 'g']);
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

  it('moves a quantity by half a serving or ten grams with the arrows, from a round number', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withBread()),
      'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
    });
    renderApp();
    const field = await screen.findByLabelText('Quantité – Pain de mie');
    // The arrows count from `min` by `step`: from 0.01 they landed on 1.01, 2.01...
    expect(field).toHaveAttribute('min', '0');
    expect(field).toHaveAttribute('step', '0.5');

    const add = screen.getByLabelText('Ajouter un produit – Déjeuner');
    fireEvent.change(add, { target: { value: BREAD.barcode } });
    const lunch = screen.getByLabelText('Quantité – Déjeuner');
    expect(lunch).toHaveAttribute('min', '0');
    expect(lunch).toHaveAttribute('step', '0.5');
    fireEvent.change(add, { target: { value: MUESLI.barcode } });
    expect(lunch).toHaveAttribute('step', '10');
  });

  it('keeps any value typed in a quantity, whatever the arrows move it by', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(withBread()),
      'GET /api/v1/inventory/': ok([BREAD]),
      'PATCH /api/v1/meals/items/7': ok(withBread()),
    });
    renderApp();
    const field = await screen.findByLabelText('Quantité – Pain de mie');

    fireEvent.change(field, { target: { value: '0.33' } });
    fireEvent.blur(field);

    await waitFor(() =>
      expect(fetch.mock.calls.some(([, o]) => o?.method === 'PATCH')).toBe(
        true,
      ),
    );
    const [, options] = fetch.mock.calls.find(([, o]) => o?.method === 'PATCH');
    expect(JSON.parse(options.body)).toEqual({
      quantity: 0.33,
      unit: 'serving',
    });
  });

  it('puts back what is saved when a quantity is left at 0', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(withBread()),
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    renderApp();
    const field = await screen.findByLabelText('Quantité – Pain de mie');

    fireEvent.change(field, { target: { value: '0' } });
    fireEvent.blur(field);

    expect(field).toHaveValue(2);
    expect(fetch.mock.calls.some(([, o]) => o?.method === 'PATCH')).toBe(false);
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
    expect(await screen.findByLabelText('Jour')).toHaveValue('10/10/2026');
    expect(today).toBeEnabled();

    fireEvent.click(today);
    await waitFor(() =>
      expect(screen.getByLabelText('Jour')).toHaveValue('09/10/2026'),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Jour précédent' }));
    await waitFor(() =>
      expect(screen.getByLabelText('Jour')).toHaveValue('08/10/2026'),
    );
  });

  it('opens on the day the address names, as when the page is loaded again', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/meals/2026-10-12': ok(day({ day: '2026-10-12' })),
      'GET /api/v1/inventory/': ok([BREAD]),
    });

    renderApp({ search: '?day=2026-10-12' });

    expect(await screen.findByLabelText('Jour')).toHaveValue('12/10/2026');
    await screen.findByRole('region', { name: 'Déjeuner' });
    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/meals/2026-10-12',
      expect.anything(),
    );
    expect(fetch).not.toHaveBeenCalledWith(DAY_URL, expect.anything());
    expect(screen.getByRole('button', { name: 'Aujourd’hui' })).toBeEnabled();
  });

  it('opens on today when the address names no day, or none that exists', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD]),
    });

    for (const search of ['', '?day=demain', '?day=2026-02-30', '?day=']) {
      const { unmount } = renderApp({ search });
      expect(await screen.findByLabelText('Jour')).toHaveValue('09/10/2026');
      await screen.findByRole('region', { name: 'Déjeuner' });
      unmount();
    }
  });

  it('keeps the day in the address, and takes it out for today', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/meals/2026-10-10': ok(day({ day: '2026-10-10' })),
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    renderApp({ search: '?other=1' });
    await screen.findByRole('region', { name: 'Déjeuner' });
    expect(window.location.search).toBe('?other=1');

    fireEvent.click(screen.getByRole('button', { name: 'Jour suivant' }));
    await waitFor(() =>
      expect(window.location.search).toBe('?other=1&day=2026-10-10'),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Aujourd’hui' }));
    await waitFor(() => expect(window.location.search).toBe('?other=1'));
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
    fireEvent.click(within(summary).getByRole('button', { name: 'Tableau' }));
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
    fireEvent.click(within(summary).getByRole('button', { name: 'Tableau' }));
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
    fireEvent.click(within(summary).getByRole('button', { name: 'Tableau' }));
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
