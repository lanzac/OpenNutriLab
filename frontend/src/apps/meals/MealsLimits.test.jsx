import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  BREAD,
  COMPOTE,
  DAY_URL,
  MUESLI,
  day,
  ok,
  renderApp,
  stubFetch,
} from './fixtures.jsx';

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const MEALS = ['Petit-déjeuner', 'Déjeuner', 'Collation', 'Dîner'];
const LIMITS_URL = '/api/v1/meals/limits/';
const putUrl = (product) => `PUT ${LIMITS_URL}${product.barcode}`;

/** What was written, in order: the URL and the body of each PUT. */
const written = (fetch) =>
  fetch.mock.calls
    .filter(([, options]) => options?.method === 'PUT')
    .map(([url, options]) => [url, JSON.parse(options.body)]);

const use = (name) => `Utiliser dans le jour proposé – ${name}`;

const open = async () => {
  renderApp();
  const summary = await screen.findByText('Limites pour le jour proposé');
  const limits = summary.closest('details');
  limits.open = true;
  // The limits are fetched once the section is there: read them when they are.
  await waitFor(() =>
    expect(within(limits).queryByText('Chargement…')).toBeNull(),
  );
  return limits;
};

describe('the limits of the products', () => {
  it('starts with every product in use, in every meal, as no limit looks like', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
    });

    const limits = await open();

    expect(within(limits).getByLabelText(use('Pain de mie'))).toBeChecked();
    for (const meal of MEALS) {
      expect(
        within(limits).getByLabelText(`${meal} – Pain de mie`),
      ).toBeChecked();
    }
    expect(
      within(limits).getByLabelText('Au plus par jour – Pain de mie'),
    ).toHaveValue(null);
  });

  it('names the serving of a product as its label does', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD, COMPOTE]),
    });

    const limits = await open();

    for (const [product, name] of [
      [BREAD, '1 tranche'],
      [COMPOTE, '1 pot'],
    ]) {
      expect(
        within(within(limits).getByLabelText(`Unité – ${product.name}`))
          .getAllByRole('option')
          .map((o) => o.textContent),
      ).toEqual([name, 'g']);
    }
  });

  it('shows the limits already set', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`GET ${LIMITS_URL}`]: ok([
        {
          barcode: BREAD.barcode,
          meals: ['breakfast', 'snack'],
          max_quantity: '4.00',
          max_unit: 'serving',
          use_all: false,
          enabled: true,
        },
      ]),
    });

    const limits = await open();

    expect(
      within(limits).getByLabelText('Déjeuner – Pain de mie'),
    ).not.toBeChecked();
    expect(
      within(limits).getByLabelText('Petit-déjeuner – Pain de mie'),
    ).toBeChecked();
    expect(
      within(limits).getByLabelText('Collation – Pain de mie'),
    ).toBeChecked();
    expect(
      within(limits).getByLabelText('Au plus par jour – Pain de mie'),
    ).toHaveValue(4);
    expect(within(limits).getByLabelText('Unité – Pain de mie')).toHaveValue(
      'serving',
    );
  });

  it('moves the most by half a serving or ten grams with the arrows, from a round number', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [putUrl(BREAD)]: ok({}),
    });
    const limits = await open();
    const most = within(limits).getByLabelText(
      'Au plus par jour – Pain de mie',
    );

    expect(most).toHaveAttribute('min', '0');
    expect(most).toHaveAttribute('step', '0.5');

    fireEvent.change(within(limits).getByLabelText('Unité – Pain de mie'), {
      target: { value: 'g' },
    });
    expect(most).toHaveAttribute('step', '10');
  });

  describe('saved as they are made', () => {
    it('saves a meal ticked at once, with no button to press, and says so', async () => {
      const fetch = stubFetch({
        [`GET ${DAY_URL}`]: ok(day()),
        'GET /api/v1/inventory/': ok([BREAD]),
        [putUrl(BREAD)]: ok({}),
      });
      const limits = await open();

      fireEvent.click(within(limits).getByLabelText('Déjeuner – Pain de mie'));

      expect(await within(limits).findByText('Enregistré')).toBeInTheDocument();
      expect(
        within(limits).queryByRole('button', { name: /Enregistrer/ }),
      ).toBeNull();
      const [[url, body]] = written(fetch);
      expect(url).toBe(`${LIMITS_URL}${BREAD.barcode}`);
      expect(body).toEqual({
        meals: ['breakfast', 'snack', 'dinner'],
        max_quantity: null,
        max_unit: null,
        use_all: false,
        enabled: true,
      });
      const [, options] = fetch.mock.calls.find(([, o]) => o?.method === 'PUT');
      expect(options.headers['X-CSRFToken']).toBe('test-csrf-token');
    });

    it('saves the most when the field is left, once, with what was typed', async () => {
      const fetch = stubFetch({
        [`GET ${DAY_URL}`]: ok(day()),
        'GET /api/v1/inventory/': ok([BREAD]),
        [putUrl(BREAD)]: ok({}),
      });
      const limits = await open();
      const most = within(limits).getByLabelText(
        'Au plus par jour – Pain de mie',
      );

      fireEvent.change(most, { target: { value: '1' } });
      fireEvent.change(most, { target: { value: '12' } });
      expect(written(fetch)).toEqual([]);
      fireEvent.blur(most);

      // At once, not after the pause in typing.
      await waitFor(() => expect(written(fetch)).toHaveLength(1), {
        timeout: 300,
      });
      await within(limits).findByText('Enregistré');
      expect(written(fetch).map(([, body]) => body)).toEqual([
        {
          meals: [],
          max_quantity: 12,
          max_unit: 'serving',
          use_all: false,
          enabled: true,
        },
      ]);
    });

    it('saves the most after a pause in typing, without the field being left', async () => {
      const fetch = stubFetch({
        [`GET ${DAY_URL}`]: ok(day()),
        'GET /api/v1/inventory/': ok([BREAD]),
        [putUrl(BREAD)]: ok({}),
      });
      const limits = await open();
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });

      fireEvent.change(
        within(limits).getByLabelText('Au plus par jour – Pain de mie'),
        { target: { value: '3' } },
      );
      await vi.advanceTimersByTimeAsync(300);
      expect(written(fetch)).toEqual([]);
      await vi.advanceTimersByTimeAsync(500);

      expect(written(fetch).map(([, body]) => body.max_quantity)).toEqual([3]);
    });

    it('saves a unit chosen at once', async () => {
      const fetch = stubFetch({
        [`GET ${DAY_URL}`]: ok(day()),
        'GET /api/v1/inventory/': ok([BREAD]),
        [putUrl(BREAD)]: ok({}),
      });
      const limits = await open();
      const most = within(limits).getByLabelText(
        'Au plus par jour – Pain de mie',
      );
      fireEvent.change(most, { target: { value: '100' } });
      fireEvent.blur(most);

      fireEvent.change(within(limits).getByLabelText('Unité – Pain de mie'), {
        target: { value: 'g' },
      });

      await waitFor(() => expect(written(fetch)).toHaveLength(2));
      expect(written(fetch)[1][1]).toMatchObject({
        max_quantity: 100,
        max_unit: 'g',
      });
    });

    it('saves every meal and no most as no limit at all', async () => {
      const fetch = stubFetch({
        [`GET ${DAY_URL}`]: ok(day()),
        'GET /api/v1/inventory/': ok([BREAD]),
        [putUrl(BREAD)]: ok({}),
      });
      const limits = await open();
      const lunch = within(limits).getByLabelText('Déjeuner – Pain de mie');

      fireEvent.click(lunch);
      fireEvent.click(lunch);

      await waitFor(() => expect(written(fetch)).toHaveLength(2));
      expect(written(fetch)[1][1]).toEqual({
        meals: [],
        max_quantity: null,
        max_unit: null,
        use_all: false,
        enabled: true,
      });
    });

    it('writes one change after the other, in the order they were made', async () => {
      let release;
      const fetch = stubFetch({
        [`GET ${DAY_URL}`]: ok(day()),
        'GET /api/v1/inventory/': ok([BREAD]),
        [putUrl(BREAD)]: () =>
          new Promise((resolve) => {
            release = () => resolve(ok({}));
          }),
      });
      const limits = await open();

      fireEvent.click(within(limits).getByLabelText('Déjeuner – Pain de mie'));
      fireEvent.click(within(limits).getByLabelText('Dîner – Pain de mie'));
      await new Promise((resolve) => setTimeout(resolve, 20));

      // The second waits for the first: the last to be heard is the last made.
      expect(written(fetch)).toHaveLength(1);
      release();
      await waitFor(() => expect(written(fetch)).toHaveLength(2));
      release();
      await within(limits).findByText('Enregistré');
      expect(written(fetch)[1][1].meals).toEqual(['breakfast', 'snack']);
    });

    it('says so when a change cannot be saved, and shows what the server has', async () => {
      vi.spyOn(console, 'error').mockImplementation(() => {});
      const fetch = stubFetch({
        [`GET ${DAY_URL}`]: ok(day()),
        'GET /api/v1/inventory/': ok([BREAD]),
        [putUrl(BREAD)]: { ok: false, status: 422 },
      });
      const limits = await open();

      fireEvent.click(within(limits).getByLabelText(use('Pain de mie')));

      expect(await within(limits).findByRole('alert')).toHaveTextContent(
        'Le changement n’a pas pu être enregistré.',
      );
      // The limits are read again: the product is in use, as the server has it.
      await waitFor(() =>
        expect(within(limits).getByLabelText(use('Pain de mie'))).toBeChecked(),
      );
      expect(
        fetch.mock.calls.filter(([url]) => url === LIMITS_URL),
      ).toHaveLength(2);
    });

    it('does not propose a day before the limits it should follow are written', async () => {
      let release;
      const fetch = stubFetch({
        [`GET ${DAY_URL}`]: ok({ ...day(), needs: [], ratios: [] }),
        'GET /api/v1/inventory/': ok([BREAD]),
        [putUrl(BREAD)]: () =>
          new Promise((resolve) => {
            release = () => resolve(ok({}));
          }),
        [`POST ${DAY_URL}/propose`]: { ok: false, status: 422 },
      });
      vi.spyOn(console, 'error').mockImplementation(() => {});
      const limits = await open();
      fireEvent.click(within(limits).getByLabelText(use('Pain de mie')));
      await waitFor(() => expect(written(fetch)).toHaveLength(1));

      fireEvent.click(screen.getByRole('button', { name: /Proposer un jour/ }));
      await new Promise((resolve) => setTimeout(resolve, 20));
      const proposed = () =>
        fetch.mock.calls.filter(([url]) => url.endsWith('/propose'));
      expect(proposed()).toHaveLength(0);
      release();

      await waitFor(() => expect(proposed()).toHaveLength(1));
    });
  });

  describe('the switch of a product', () => {
    it('leaves the product out and greys what is set of it, keeping it', async () => {
      const fetch = stubFetch({
        [`GET ${DAY_URL}`]: ok(day()),
        'GET /api/v1/inventory/': ok([BREAD]),
        [`GET ${LIMITS_URL}`]: ok([
          {
            barcode: BREAD.barcode,
            meals: ['lunch'],
            max_quantity: '4.00',
            max_unit: 'serving',
            use_all: false,
            enabled: true,
          },
        ]),
        [putUrl(BREAD)]: ok({}),
      });
      const limits = await open();

      fireEvent.click(within(limits).getByLabelText(use('Pain de mie')));

      await within(limits).findByText('Enregistré');
      expect(written(fetch)[0][1]).toEqual({
        meals: ['lunch'],
        max_quantity: 4,
        max_unit: 'serving',
        use_all: false,
        enabled: false,
      });
      expect(
        within(limits).getByLabelText(use('Pain de mie')),
      ).not.toBeChecked();
      for (const meal of MEALS) {
        expect(
          within(limits).getByLabelText(`${meal} – Pain de mie`),
        ).toBeDisabled();
      }
      expect(
        within(limits).getByLabelText('Au plus par jour – Pain de mie'),
      ).toBeDisabled();
      expect(
        within(limits).getByLabelText('Au plus par jour – Pain de mie'),
      ).toHaveValue(4);
      expect(
        within(limits).getByLabelText('Utiliser tout le paquet – Pain de mie'),
      ).toBeDisabled();
      // Put back, it is as it was.
      fireEvent.click(within(limits).getByLabelText(use('Pain de mie')));
      expect(
        within(limits).getByLabelText('Au plus par jour – Pain de mie'),
      ).toBeEnabled();
      expect(
        within(limits).getByLabelText('Déjeuner – Pain de mie'),
      ).toBeChecked();
      await waitFor(() => expect(written(fetch)).toHaveLength(2));
      expect(written(fetch)[1][1]).toMatchObject({
        meals: ['lunch'],
        max_quantity: 4,
        enabled: true,
      });
    });

    it('shows a product already left out', async () => {
      stubFetch({
        [`GET ${DAY_URL}`]: ok(day()),
        'GET /api/v1/inventory/': ok([BREAD]),
        [`GET ${LIMITS_URL}`]: ok([
          {
            barcode: BREAD.barcode,
            meals: [],
            max_quantity: null,
            max_unit: '',
            use_all: false,
            enabled: false,
          },
        ]),
      });

      const limits = await open();

      expect(
        within(limits).getByLabelText(use('Pain de mie')),
      ).not.toBeChecked();
      expect(
        within(limits).getByLabelText('Déjeuner – Pain de mie'),
      ).toBeDisabled();
    });

    it('does not let the last meal be unticked, and says what to use instead', async () => {
      const fetch = stubFetch({
        [`GET ${DAY_URL}`]: ok(day()),
        'GET /api/v1/inventory/': ok([MUESLI]),
        [putUrl(MUESLI)]: ok({}),
      });
      const limits = await open();
      const unit = within(limits).getByLabelText('Unité – Muesli');
      expect(
        within(unit)
          .getAllByRole('option')
          .map((o) => o.textContent),
      ).toEqual(['g']);

      for (const meal of MEALS.slice(0, 3)) {
        fireEvent.click(within(limits).getByLabelText(`${meal} – Muesli`));
      }

      const last = within(limits).getByLabelText('Dîner – Muesli');
      expect(last).toBeDisabled();
      expect(last.closest('label')).toHaveAttribute(
        'title',
        'Un produit a besoin d’un repas : utilisez l’interrupteur pour l’écarter.',
      );
      await waitFor(() => expect(written(fetch)).toHaveLength(3));
    });
  });

  describe('the switch of all the products', () => {
    const twoProducts = (answer = []) => ({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
      [`GET ${LIMITS_URL}`]: ok(answer),
      [`PUT ${LIMITS_URL}`]: ok([]),
    });

    it('is on when every product is in use, and says how many are', async () => {
      stubFetch(twoProducts());

      const limits = await open();

      expect(within(limits).getByLabelText('Tous les produits')).toBeChecked();
      expect(within(limits).getByText('2 sur 2 utilisés')).toBeInTheDocument();
    });

    it('leaves every product out, then puts them all back, in one request each', async () => {
      const fetch = stubFetch(twoProducts());
      const limits = await open();
      const all = within(limits).getByLabelText('Tous les produits');

      fireEvent.click(all);

      expect(all).not.toBeChecked();
      expect(within(limits).getByText('0 sur 2 utilisés')).toBeInTheDocument();
      expect(
        within(limits).getByLabelText(use('Pain de mie')),
      ).not.toBeChecked();
      expect(within(limits).getByLabelText(use('Muesli'))).not.toBeChecked();
      await within(limits).findByText('Enregistré');
      fireEvent.click(all);

      expect(all).toBeChecked();
      expect(within(limits).getByLabelText(use('Muesli'))).toBeChecked();
      await waitFor(() => expect(written(fetch)).toHaveLength(2));
      expect(written(fetch)).toEqual([
        [LIMITS_URL, { enabled: false }],
        [LIMITS_URL, { enabled: true }],
      ]);
    });

    it('is off when one is out, and puts them all in when pressed', async () => {
      const fetch = stubFetch(
        twoProducts([
          {
            barcode: MUESLI.barcode,
            meals: [],
            max_quantity: null,
            max_unit: '',
            use_all: false,
            enabled: false,
          },
        ]),
      );
      const limits = await open();
      const all = within(limits).getByLabelText('Tous les produits');
      expect(all).not.toBeChecked();
      expect(within(limits).getByText('1 sur 2 utilisés')).toBeInTheDocument();

      fireEvent.click(all);

      expect(all).toBeChecked();
      expect(within(limits).getByLabelText(use('Muesli'))).toBeChecked();
      await waitFor(() => expect(written(fetch)).toHaveLength(1));
      expect(written(fetch)[0][1]).toEqual({ enabled: true });
    });

    it('keeps what was set of each product while they are out', async () => {
      stubFetch(
        twoProducts([
          {
            barcode: BREAD.barcode,
            meals: ['lunch'],
            max_quantity: '4.00',
            max_unit: 'serving',
            use_all: false,
            enabled: true,
          },
        ]),
      );
      const limits = await open();

      fireEvent.click(within(limits).getByLabelText('Tous les produits'));

      expect(
        within(limits).getByLabelText('Au plus par jour – Pain de mie'),
      ).toHaveValue(4);
      expect(
        within(limits).getByLabelText('Dîner – Pain de mie'),
      ).not.toBeChecked();
    });
  });

  describe('the groups', () => {
    const NOBODYS = {
      ...MUESLI,
      barcode: '3000000000001',
      name: 'Mystère',
      group_level_1: '',
      group_level_2: '',
    };

    it('cuts the products into the food groups they are filed under', async () => {
      stubFetch({
        [`GET ${DAY_URL}`]: ok(day()),
        'GET /api/v1/inventory/': ok([COMPOTE, NOBODYS, MUESLI, BREAD]),
      });

      const limits = await open();

      const groups = [...limits.querySelectorAll('tbody')].map((body) => ({
        name: body.querySelector('th[scope="colgroup"]').textContent.trim(),
        products: [...body.querySelectorAll('label.form-check-label')].map(
          (label) => label.textContent,
        ),
      }));
      // By the name shown, the products with no group last, each group by name.
      expect(groups).toEqual([
        {
          name: 'Céréales et pommes de terre 2',
          products: ['Muesli', 'Pain de mie'],
        },
        { name: 'Fruits et légumes 1', products: ['Compote'] },
        { name: 'Non classé 1', products: ['Mystère'] },
      ]);
    });
  });

  describe('the whole package', () => {
    it('is asked for in place of a most', async () => {
      const fetch = stubFetch({
        [`GET ${DAY_URL}`]: ok(day()),
        'GET /api/v1/inventory/': ok([BREAD]),
        [putUrl(BREAD)]: ok({}),
      });
      const limits = await open();
      const most = within(limits).getByLabelText(
        'Au plus par jour – Pain de mie',
      );
      fireEvent.change(most, { target: { value: '3' } });
      fireEvent.blur(most);

      fireEvent.click(
        within(limits).getByLabelText('Utiliser tout le paquet – Pain de mie'),
      );

      // The package is the quantity: no other most can be given.
      expect(most).toBeDisabled();
      expect(
        within(limits).getByLabelText('Unité – Pain de mie'),
      ).toBeDisabled();
      await waitFor(() => expect(written(fetch)).toHaveLength(2));
      expect(written(fetch)[1][1]).toEqual({
        meals: [],
        max_quantity: null,
        max_unit: null,
        use_all: true,
        enabled: true,
      });
    });

    it('gives the most back when it is not asked for any more', async () => {
      stubFetch({
        [`GET ${DAY_URL}`]: ok(day()),
        'GET /api/v1/inventory/': ok([BREAD]),
        [putUrl(BREAD)]: ok({}),
      });
      const limits = await open();
      const whole = within(limits).getByLabelText(
        'Utiliser tout le paquet – Pain de mie',
      );
      fireEvent.click(whole);

      fireEvent.click(whole);

      expect(whole).not.toBeChecked();
      expect(
        within(limits).getByLabelText('Au plus par jour – Pain de mie'),
      ).toBeEnabled();
    });

    it('is shown when it is already asked for', async () => {
      stubFetch({
        [`GET ${DAY_URL}`]: ok(day()),
        'GET /api/v1/inventory/': ok([BREAD]),
        [`GET ${LIMITS_URL}`]: ok([
          {
            barcode: BREAD.barcode,
            meals: ['lunch'],
            max_quantity: null,
            max_unit: '',
            use_all: true,
            enabled: true,
          },
        ]),
      });
      const limits = await open();

      expect(
        within(limits).getByLabelText('Utiliser tout le paquet – Pain de mie'),
      ).toBeChecked();
      expect(
        within(limits).getByLabelText('Au plus par jour – Pain de mie'),
      ).toBeDisabled();
      expect(
        within(limits).getByLabelText('Déjeuner – Pain de mie'),
      ).toBeChecked();
      expect(
        within(limits).getByLabelText('Dîner – Pain de mie'),
      ).not.toBeChecked();
    });

    it('cannot be asked for of a product with no total quantity', async () => {
      stubFetch({
        [`GET ${DAY_URL}`]: ok(day()),
        'GET /api/v1/inventory/': ok([{ ...MUESLI, package: null }]),
        // Nothing is kept of a request that cannot be made now.
        [`GET ${LIMITS_URL}`]: ok([
          {
            barcode: MUESLI.barcode,
            meals: [],
            max_quantity: null,
            max_unit: '',
            use_all: true,
            enabled: true,
          },
        ]),
      });
      const limits = await open();

      const whole = within(limits).getByLabelText(
        'Utiliser tout le paquet – Muesli',
      );

      expect(whole).toBeDisabled();
      expect(whole).not.toBeChecked();
      expect(whole.closest('label')).toHaveAttribute(
        'title',
        'Indiquez d’abord la quantité totale du produit.',
      );
      expect(
        within(limits).getByLabelText('Au plus par jour – Muesli'),
      ).toBeEnabled();
    });
  });

  it('is not there when the inventory is empty', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([]),
    });
    renderApp();
    await screen.findByRole('region', { name: 'Déjeuner' });

    expect(screen.queryByText('Limites pour le jour proposé')).toBeNull();
  });
});
