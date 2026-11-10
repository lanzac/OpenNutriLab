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
  addFromPicker,
  breadItem,
  day,
  labels,
  meal,
  need,
  ok,
  openItem,
  openPicker,
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

  it('says a meal in a line, with its energy, and keeps the fields and the nutrition folded', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withBread()),
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    renderApp();

    const breakfast = await screen.findByRole('region', {
      name: 'Petit-déjeuner',
    });
    // The item as a phrase, and the energy of the meal in its head: 3766.68 kJ is 900 kcal.
    const line = within(breakfast).getByRole('button', {
      name: /^Pain de mie/,
    });
    expect(line).toHaveTextContent('2 × 1 tranche · 71,4 g');
    expect(line).toHaveAttribute('aria-expanded', 'false');
    expect(within(breakfast).getByText('900 kcal')).toBeInTheDocument();
    // Nothing to change and no table until they are asked for.
    expect(
      within(breakfast).queryByLabelText('Quantité – Pain de mie'),
    ).toBeNull();
    expect(within(breakfast).queryByText('7,85 g')).toBeNull();

    // The line opens the fields.
    fireEvent.click(line);
    expect(
      within(breakfast).getByLabelText('Quantité – Pain de mie'),
    ).toHaveValue(2);
    fireEvent.click(line);
    expect(
      within(breakfast).queryByLabelText('Quantité – Pain de mie'),
    ).toBeNull();
  });

  it('opens the nutrition of a meal, with the interval and the coverage on a figure, and keeps it open', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withBread()),
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    const { unmount } = renderApp();
    const breakfast = await screen.findByRole('region', {
      name: 'Petit-déjeuner',
    });

    fireEvent.click(
      within(breakfast).getByRole('button', { name: 'Nutrition de ce repas' }),
    );
    expect(within(breakfast).getByText('7,85 g')).toBeInTheDocument();
    // The energy is twice on the card: in its head, and in its table, where it has the range.
    expect(within(breakfast).getAllByText('900 kcal')[1]).toHaveAttribute(
      'title',
      expect.stringContaining('884 – 908'),
    );

    // Seen again, it is as it was left.
    unmount();
    renderApp();
    const again = await screen.findByRole('region', { name: 'Petit-déjeuner' });
    expect(within(again).getByText('7,85 g')).toBeInTheDocument();
  });

  it('puts a product in a meal by the window, with the CSRF token, one serving to begin with', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
      [`POST ${DAY_URL}/breakfast/items`]: ok(withBread()),
    });
    renderApp();
    const breakfast = await screen.findByRole('region', {
      name: 'Petit-déjeuner',
    });

    await addFromPicker('Petit-déjeuner', 'Pain de mie');

    // The product is in the meal, and the window stays for the next one.
    expect(
      await within(breakfast).findByRole('button', { name: /^Pain de mie/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    const [, options] = fetch.mock.calls.find(([, o]) => o?.method === 'POST');
    expect(JSON.parse(options.body)).toEqual({
      barcode: BREAD.barcode,
      quantity: 1,
      unit: 'serving',
    });
    expect(options.headers['X-CSRFToken']).toBe('test-csrf-token');
  });

  it('counts a product with no serving in 100 g to begin with', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([MUESLI]),
      [`POST ${DAY_URL}/lunch/items`]: ok(day()),
    });
    renderApp();
    await screen.findByRole('region', { name: 'Déjeuner' });

    await addFromPicker('Déjeuner', 'Muesli');

    await waitFor(() =>
      expect(fetch.mock.calls.some(([, o]) => o?.method === 'POST')).toBe(true),
    );
    const [, options] = fetch.mock.calls.find(([, o]) => o?.method === 'POST');
    expect(JSON.parse(options.body)).toEqual({
      barcode: MUESLI.barcode,
      quantity: 100,
      unit: 'g',
    });
  });

  it('shows in the window what a product is, and marks what is already in the meal', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withBread()),
      'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
    });
    renderApp();
    await screen.findByRole('region', { name: 'Petit-déjeuner' });

    const dialog = await openPicker('Petit-déjeuner');

    expect(dialog).toHaveAccessibleName('Ajouter à : Petit-déjeuner');
    // Its serving and what its package holds, under the name.
    const bread = within(dialog).getByRole('button', { name: /^Pain de mie/ });
    expect(bread).toHaveTextContent('1 tranche (35,7 g) · 500 g');
    expect(bread).toBeDisabled();
    expect(bread).toHaveTextContent('Dans ce repas');
    const muesli = within(dialog).getByRole('button', { name: /^Muesli/ });
    expect(muesli).toHaveTextContent('375 g');
    expect(muesli).toBeEnabled();
  });

  it('sorts the products of the window by food group, and filters them by group or by what is typed', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD, COMPOTE, MUESLI]),
    });
    renderApp();
    await screen.findByRole('region', { name: 'Déjeuner' });
    const dialog = await openPicker('Déjeuner');
    const names = () =>
      within(dialog)
        .getAllByRole('button', { name: /^(Pain|Muesli|Compote)/ })
        .map((b) => b.textContent.split(/\d/)[0].trim());

    // The groups, in the language served, with their products by name.
    // Each is a filter and, while all are shown, a title over its products.
    expect(
      within(dialog).getAllByText('Céréales et pommes de terre'),
    ).toHaveLength(2);
    expect(within(dialog).getAllByText('Fruits et légumes')).toHaveLength(2);
    expect(names()).toEqual(['Muesli', 'Pain de mie', 'Compote']);

    // A group.
    fireEvent.click(
      within(dialog).getByRole('button', { name: /^Fruits et légumes/ }),
    );
    expect(names()).toEqual(['Compote']);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Tous' }));
    expect(names()).toHaveLength(3);

    // A word, found without regard to accents or capitals.
    fireEvent.change(within(dialog).getByLabelText('Rechercher un produit'), {
      target: { value: 'MUES' },
    });
    expect(names()).toEqual(['Muesli']);
    fireEvent.change(within(dialog).getByLabelText('Rechercher un produit'), {
      target: { value: 'zzz' },
    });
    expect(
      within(dialog).getByText('Aucun produit ne correspond.'),
    ).toBeVisible();
  });

  it('shows the photo of a product, and a placeholder for one with none', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([
        { ...BREAD, image: '/media/bread.jpg' },
        MUESLI,
      ]),
    });
    renderApp();
    await screen.findByRole('region', { name: 'Déjeuner' });
    const dialog = await openPicker('Déjeuner');

    const photoOf = (name) =>
      within(
        within(dialog).getByRole('button', { name: new RegExp(`^${name}`) }),
      )
        .getByRole('presentation')
        .getAttribute('src');
    expect(photoOf('Pain de mie')).toBe('/media/bread.jpg');
    expect(photoOf('Muesli')).toBe('/static/placeholder.png');
  });

  it('closes the window with its button, with Escape and with a click beside it', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    renderApp();
    await screen.findByRole('region', { name: 'Déjeuner' });

    const dialog = await openPicker('Déjeuner');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Terminé' }));
    expect(screen.queryByRole('dialog')).toBeNull();

    fireEvent.keyDown(await openPicker('Déjeuner'), { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();

    const again = await openPicker('Déjeuner');
    fireEvent.mouseDown(again.parentElement);
    expect(screen.queryByRole('dialog')).toBeNull();
    // The page is where it was.
    expect(
      screen.getByRole('button', { name: 'Ajouter un produit – Déjeuner' }),
    ).toHaveFocus();
  });

  it('offers no way to add where the inventory is empty', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([]),
    });
    renderApp();
    await screen.findByRole('region', { name: 'Déjeuner' });

    expect(
      screen.queryByRole('button', { name: /Ajouter un produit/ }),
    ).toBeNull();
  });

  it("names a product's serving as its label does, in a meal and in the window", async () => {
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
    await openItem('Pain de mie', within(breakfast));

    // The item of the meal: the name of the label, with what it weighs.
    expect(
      within(within(breakfast).getByLabelText('Unité – Pain de mie'))
        .getAllByRole('option')
        .map((o) => o.textContent),
    ).toEqual(['1 tranche (35,7 g)', 'g']);

    // The products being added, named or not.
    const dialog = await openPicker('Déjeuner');
    expect(
      within(dialog).getByRole('button', { name: /^Compote/ }),
    ).toHaveTextContent('1 pot (100 g)');
    expect(
      within(dialog).getByRole('button', { name: /^Barre/ }),
    ).toHaveTextContent('portion (30 g)');
  });

  it('changes a quantity when the field is left, and not when it did not change', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(withBread()),
      'GET /api/v1/inventory/': ok([BREAD]),
      'PATCH /api/v1/meals/items/7': ok(withBread()),
    });
    renderApp();
    await openItem('Pain de mie');
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

  it('keeps the fields of an item open when its quantity has been changed', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withBread()),
      'GET /api/v1/inventory/': ok([BREAD]),
      'PATCH /api/v1/meals/items/7': ok(
        withBread({
          meals: [
            meal('breakfast', 'Petit-déjeuner', [
              { ...breadItem, quantity: '3.00' },
            ]),
          ],
        }),
      ),
    });
    renderApp();
    await openItem('Pain de mie');
    const field = await screen.findByLabelText('Quantité – Pain de mie');

    fireEvent.change(field, { target: { value: '3' } });
    fireEvent.blur(field);

    // The day it answers with shows 3, and the fields are still there to change again.
    await waitFor(() =>
      expect(screen.getByLabelText('Quantité – Pain de mie')).toHaveValue(3),
    );
    expect(
      screen.getByRole('button', { name: /^Pain de mie/ }),
    ).toHaveAttribute('aria-expanded', 'true');
  });

  it('moves a quantity by half a serving or ten grams with the arrows, from a round number', async () => {
    const muesliItem = {
      ...breadItem,
      id: 8,
      barcode: MUESLI.barcode,
      name: 'Muesli',
      quantity: '100.00',
      unit: 'g',
      serving: null,
    };
    stubFetch({
      [`GET ${DAY_URL}`]: ok(
        withBread({
          meals: [
            meal('breakfast', 'Petit-déjeuner', [breadItem]),
            meal('lunch', 'Déjeuner', [muesliItem]),
          ],
        }),
      ),
      'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
    });
    renderApp();
    await openItem('Pain de mie');
    await openItem('Muesli');

    // The arrows count from `min` by `step`: from 0.01 they landed on 1.01, 2.01...
    const servings = await screen.findByLabelText('Quantité – Pain de mie');
    expect(servings).toHaveAttribute('min', '0');
    expect(servings).toHaveAttribute('step', '0.5');
    const grams = screen.getByLabelText('Quantité – Muesli');
    expect(grams).toHaveAttribute('min', '0');
    expect(grams).toHaveAttribute('step', '10');
  });

  it('keeps any value typed in a quantity, whatever the arrows move it by', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(withBread()),
      'GET /api/v1/inventory/': ok([BREAD]),
      'PATCH /api/v1/meals/items/7': ok(withBread()),
    });
    renderApp();
    await openItem('Pain de mie');
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
    await openItem('Pain de mie');
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
    await openItem('Pain de mie');

    // The limits below have a unit for the product too.
    const breakfast = screen.getByRole('region', { name: 'Petit-déjeuner' });
    fireEvent.change(within(breakfast).getByLabelText('Unité – Pain de mie'), {
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
    await openItem('Pain de mie');

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
    await openItem('Pain de mie');

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
