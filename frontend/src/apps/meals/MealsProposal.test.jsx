import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  BREAD,
  DAY_URL,
  MUESLI,
  day,
  need,
  ok,
  ratio,
  renderApp,
  stubFetch,
  withBread,
} from './fixtures.jsx';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const PROPOSE_URL = `${DAY_URL}/propose`;

// The day a proposal makes: bread at breakfast, with no id as it is not saved.
const proposedDay = () => {
  const found = withBread({
    needs: [need({ status: 'within', certain: true })],
    ratios: [ratio({})],
  });
  found.meals[0].items = found.meals[0].items.map((item) => ({
    ...item,
    id: null,
  }));
  return found;
};

const proposal = (overrides = {}) => ({
  status: 'optimal',
  objective: 1.5,
  items: [
    {
      kind: 'breakfast',
      barcode: BREAD.barcode,
      quantity: '2.00',
      unit: 'serving',
    },
  ],
  skipped: [],
  day: proposedDay(),
  ...overrides,
});

// A day with a profile, so that there is something to propose it for.
const withProfile = (found = day()) => ({ ...found, needs: [], ratios: [] });

describe('proposing a day', () => {
  it('cannot be asked for without a profile, and says why', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    renderApp();

    const button = await screen.findByRole('button', {
      name: /Proposer un jour/,
    });

    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('title', 'Renseignez votre profil.');
  });

  it('shows the day proposed, saves nothing, and says what it is', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(withProfile()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`POST ${PROPOSE_URL}`]: ok(proposal()),
    });
    renderApp();

    fireEvent.click(
      await screen.findByRole('button', { name: /Proposer un jour/ }),
    );

    const panel = await screen.findByRole('region', { name: 'Jour proposé' });
    expect(
      within(panel).getByText('Le meilleur jour que permet l’inventaire.'),
    ).toBeInTheDocument();
    // The meals read only: what is in them, and nothing to change.
    expect(within(panel).getByText('Pain de mie')).toBeInTheDocument();
    expect(within(panel).getByText('2 portion (71,4 g)')).toBeInTheDocument();
    expect(within(panel).queryByRole('spinbutton')).toBeNull();
    expect(within(panel).queryByRole('button', { name: /Retirer/ })).toBeNull();
    // The day against the needs, as for a day that is saved.
    expect(
      within(panel).getByRole('region', {
        name: 'La journée face à vos besoins',
      }),
    ).toBeInTheDocument();
    // Asked once, with the CSRF token, and nothing written.
    const posts = fetch.mock.calls.filter(([, o]) => o?.method === 'POST');
    expect(posts).toHaveLength(1);
    expect(posts[0][1].headers['X-CSRFToken']).toBe('test-csrf-token');
    expect(
      fetch.mock.calls.some(([, o]) => o?.method === 'PUT' && o.body),
    ).toBe(false);
  });

  it('says it is looking while it looks, and that the time ran out when it did', async () => {
    let answer;
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withProfile()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`POST ${PROPOSE_URL}`]: () =>
        new Promise((resolve) => {
          answer = resolve;
        }),
    });
    renderApp();

    fireEvent.click(
      await screen.findByRole('button', { name: /Proposer un jour/ }),
    );

    const looking = await screen.findByRole('button', {
      name: /Recherche du meilleur jour/,
    });
    expect(looking).toBeDisabled();
    answer(ok(proposal({ status: 'time_limit' })));
    expect(
      await screen.findByText(
        'Le temps est écoulé : voici le meilleur jour trouvé.',
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /Proposer un jour/ }),
    ).toBeEnabled();
  });

  it('names the products it left out, and shows no day when it found none', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withProfile()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`POST ${PROPOSE_URL}`]: ok(
        proposal({
          status: 'no_candidates',
          items: [],
          skipped: [
            { barcode: MUESLI.barcode, name: 'Muesli', reason: 'no_energy' },
          ],
        }),
      ),
    });
    renderApp();

    fireEvent.click(
      await screen.findByRole('button', { name: /Proposer un jour/ }),
    );

    const panel = await screen.findByRole('region', { name: 'Jour proposé' });
    expect(
      within(panel).getByText(
        'Aucun produit de l’inventaire n’a de composition.',
      ),
    ).toBeInTheDocument();
    expect(
      within(panel).getByText(/Laissés de côté.*Muesli/),
    ).toBeInTheDocument();
    expect(
      within(panel).queryByRole('button', { name: 'Utiliser ce jour' }),
    ).toBeNull();
  });

  it('puts the proposed day in place of the day when it is taken', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(withProfile()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`POST ${PROPOSE_URL}`]: ok(proposal()),
      [`PUT ${DAY_URL}`]: ok(withBread({ needs: [], ratios: [] })),
    });
    const confirm = vi.fn();
    vi.stubGlobal('confirm', confirm);
    renderApp();
    fireEvent.click(
      await screen.findByRole('button', { name: /Proposer un jour/ }),
    );
    const panel = await screen.findByRole('region', { name: 'Jour proposé' });

    fireEvent.click(
      within(panel).getByRole('button', { name: 'Utiliser ce jour' }),
    );

    // The day shown is now the saved one, with rows to change, and the proposal is gone.
    expect(
      await screen.findByLabelText('Quantité – Pain de mie'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Jour proposé' })).toBeNull();
    const [, options] = fetch.mock.calls.find(([, o]) => o?.method === 'PUT');
    expect(JSON.parse(options.body)).toEqual({
      items: [
        {
          kind: 'breakfast',
          barcode: BREAD.barcode,
          quantity: '2.00',
          unit: 'serving',
        },
      ],
    });
    expect(options.headers['X-CSRFToken']).toBe('test-csrf-token');
    // An empty day is replaced without asking.
    expect(confirm).not.toHaveBeenCalled();
  });

  it('asks before it replaces a day that has something in it, and keeps it when refused', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(withBread({ needs: [], ratios: [] })),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`POST ${PROPOSE_URL}`]: ok(proposal()),
    });
    const confirm = vi.fn().mockReturnValue(false);
    vi.stubGlobal('confirm', confirm);
    renderApp();
    fireEvent.click(
      await screen.findByRole('button', { name: /Proposer un jour/ }),
    );
    const panel = await screen.findByRole('region', { name: 'Jour proposé' });

    fireEvent.click(
      within(panel).getByRole('button', { name: 'Utiliser ce jour' }),
    );

    expect(confirm).toHaveBeenCalledWith('Remplacer ce qui est dans ce jour ?');
    expect(fetch.mock.calls.some(([, o]) => o?.method === 'PUT')).toBe(false);
    expect(
      screen.getByRole('region', { name: 'Jour proposé' }),
    ).toBeInTheDocument();
  });

  it('closes the proposal and leaves the day alone', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withProfile()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`POST ${PROPOSE_URL}`]: ok(proposal()),
    });
    renderApp();
    fireEvent.click(
      await screen.findByRole('button', { name: /Proposer un jour/ }),
    );
    const panel = await screen.findByRole('region', { name: 'Jour proposé' });

    fireEvent.click(
      within(panel).getAllByRole('button', { name: 'Fermer' })[0],
    );

    expect(screen.queryByRole('region', { name: 'Jour proposé' })).toBeNull();
    expect(screen.getAllByText('Rien dans ce repas.')).toHaveLength(4);
  });

  it('says so when no day could be proposed', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withProfile()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`POST ${PROPOSE_URL}`]: { ok: false, status: 422 },
    });
    renderApp();

    fireEvent.click(
      await screen.findByRole('button', { name: /Proposer un jour/ }),
    );

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Aucun jour n’a pu être proposé.',
    );
    expect(screen.queryByRole('region', { name: 'Jour proposé' })).toBeNull();
  });

  it('drops a proposal when the day changes', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withProfile()),
      'GET /api/v1/meals/2026-10-10': ok(
        withProfile(day({ day: '2026-10-10' })),
      ),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`POST ${PROPOSE_URL}`]: ok(proposal()),
    });
    renderApp();
    fireEvent.click(
      await screen.findByRole('button', { name: /Proposer un jour/ }),
    );
    await screen.findByRole('region', { name: 'Jour proposé' });

    fireEvent.click(screen.getByRole('button', { name: 'Jour suivant' }));

    // Once the next day is shown: while it loads, nothing is shown anyway.
    expect(await screen.findByLabelText('Jour')).toHaveValue('2026-10-10');
    await screen.findByRole('region', { name: 'Déjeuner' });
    expect(screen.queryByRole('region', { name: 'Jour proposé' })).toBeNull();
  });
});

describe('the limits of the products', () => {
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

  it('starts with every meal for every product, as no limit looks like', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
    });

    const limits = await open();

    for (const meal of ['Petit-déjeuner', 'Déjeuner', 'Collation', 'Dîner']) {
      expect(
        within(limits).getByLabelText(`${meal} – Pain de mie`),
      ).toBeChecked();
    }
    expect(
      within(limits).getByLabelText('Au plus par jour – Pain de mie'),
    ).toHaveValue(null);
  });

  it('shows the limits already set', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD]),
      'GET /api/v1/meals/limits/': ok([
        {
          barcode: BREAD.barcode,
          meals: ['breakfast', 'snack'],
          max_quantity: '4.00',
          max_unit: 'serving',
        },
      ]),
    });

    const limits = await open();

    await waitFor(() =>
      expect(
        within(limits).getByLabelText('Déjeuner – Pain de mie'),
      ).not.toBeChecked(),
    );
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

  it('saves the meals and the most, with the CSRF token', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`PUT /api/v1/meals/limits/${BREAD.barcode}`]: ok({}),
    });
    const limits = await open();
    fireEvent.click(
      await within(limits).findByLabelText('Déjeuner – Pain de mie'),
    );
    fireEvent.click(within(limits).getByLabelText('Dîner – Pain de mie'));
    fireEvent.change(
      within(limits).getByLabelText('Au plus par jour – Pain de mie'),
      {
        target: { value: '3' },
      },
    );

    fireEvent.click(
      within(limits).getByRole('button', { name: 'Enregistrer – Pain de mie' }),
    );

    expect(await within(limits).findByText('Enregistré')).toBeInTheDocument();
    const [, options] = fetch.mock.calls.find(([, o]) => o?.method === 'PUT');
    expect(JSON.parse(options.body)).toEqual({
      meals: ['breakfast', 'snack'],
      max_quantity: 3,
      max_unit: 'serving',
      use_all: false,
    });
    expect(options.headers['X-CSRFToken']).toBe('test-csrf-token');
  });

  it('saves every meal and no most as no limit at all', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`PUT /api/v1/meals/limits/${BREAD.barcode}`]: ok({}),
    });
    const limits = await open();

    fireEvent.click(
      await within(limits).findByRole('button', {
        name: 'Enregistrer – Pain de mie',
      }),
    );

    await within(limits).findByText('Enregistré');
    const [, options] = fetch.mock.calls.find(([, o]) => o?.method === 'PUT');
    expect(JSON.parse(options.body)).toEqual({
      meals: [],
      max_quantity: null,
      max_unit: null,
      use_all: false,
    });
  });

  it('counts a product with no serving in grams only, and cannot save no meal at all', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([MUESLI]),
    });
    const limits = await open();
    const unit = await within(limits).findByLabelText('Unité – Muesli');

    expect(
      within(unit)
        .getAllByRole('option')
        .map((o) => o.textContent),
    ).toEqual(['g']);
    for (const meal of ['Petit-déjeuner', 'Déjeuner', 'Collation', 'Dîner']) {
      fireEvent.click(within(limits).getByLabelText(`${meal} – Muesli`));
    }
    expect(
      within(limits).getByRole('button', { name: 'Enregistrer – Muesli' }),
    ).toBeDisabled();
  });

  it('asks for the whole package in place of a most', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`PUT /api/v1/meals/limits/${BREAD.barcode}`]: ok({}),
    });
    const limits = await open();
    fireEvent.change(
      await within(limits).findByLabelText('Au plus par jour – Pain de mie'),
      { target: { value: '3' } },
    );

    fireEvent.click(
      within(limits).getByLabelText('Utiliser tout le paquet – Pain de mie'),
    );

    // The package is the quantity: no other most can be given.
    expect(
      within(limits).getByLabelText('Au plus par jour – Pain de mie'),
    ).toBeDisabled();
    expect(within(limits).getByLabelText('Unité – Pain de mie')).toBeDisabled();
    fireEvent.click(
      within(limits).getByRole('button', { name: 'Enregistrer – Pain de mie' }),
    );
    expect(await within(limits).findByText('Enregistré')).toBeInTheDocument();
    const [, options] = fetch.mock.calls.find(([, o]) => o?.method === 'PUT');
    expect(JSON.parse(options.body)).toEqual({
      meals: [],
      max_quantity: null,
      max_unit: null,
      use_all: true,
    });
  });

  it('gives the most back when the whole package is not asked for any more', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    const limits = await open();
    const whole = await within(limits).findByLabelText(
      'Utiliser tout le paquet – Pain de mie',
    );
    fireEvent.click(whole);

    fireEvent.click(whole);

    expect(whole).not.toBeChecked();
    expect(
      within(limits).getByLabelText('Au plus par jour – Pain de mie'),
    ).toBeEnabled();
  });

  it('shows the whole package already asked for', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD]),
      'GET /api/v1/meals/limits/': ok([
        {
          barcode: BREAD.barcode,
          meals: ['lunch'],
          max_quantity: null,
          max_unit: '',
          use_all: true,
        },
      ]),
    });
    const limits = await open();

    expect(
      await within(limits).findByLabelText(
        'Utiliser tout le paquet – Pain de mie',
      ),
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

  it('cannot ask for the whole package of a product with no total quantity', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([{ ...MUESLI, package: null }]),
      // Nothing is kept of a request that cannot be made now.
      'GET /api/v1/meals/limits/': ok([
        {
          barcode: MUESLI.barcode,
          meals: [],
          max_quantity: null,
          max_unit: '',
          use_all: true,
        },
      ]),
    });
    const limits = await open();

    const whole = await within(limits).findByLabelText(
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

  it('says so when the limits cannot be saved', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`PUT /api/v1/meals/limits/${BREAD.barcode}`]: { ok: false, status: 422 },
    });
    const limits = await open();

    fireEvent.click(
      await within(limits).findByRole('button', {
        name: 'Enregistrer – Pain de mie',
      }),
    );

    expect(await within(limits).findByRole('alert')).toHaveTextContent(
      'Le changement n’a pas pu être enregistré.',
    );
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
