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
      name: /Compléter ma journée/,
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
      await screen.findByRole('button', { name: /Compléter ma journée/ }),
    );

    const panel = await screen.findByRole('region', { name: 'Jour proposé' });
    expect(
      within(panel).getByText('Le meilleur jour que permet l’inventaire.'),
    ).toBeInTheDocument();
    // The meals read only: what is in them, and nothing to change.
    expect(within(panel).getByText('Pain de mie')).toBeInTheDocument();
    // The serving as the label names it.
    expect(
      within(panel).getByText('2 × 1 tranche · 71,4 g'),
    ).toBeInTheDocument();
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
      await screen.findByRole('button', { name: /Compléter ma journée/ }),
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
      screen.getByRole('button', { name: /Compléter ma journée/ }),
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
      await screen.findByRole('button', { name: /Compléter ma journée/ }),
    );

    const panel = await screen.findByRole('region', { name: 'Jour proposé' });
    expect(
      within(panel).getByText(/Aucun produit de l’inventaire ne peut composer/),
    ).toBeInTheDocument();
    expect(
      within(panel).getByText(/Laissés de côté, sans valeur d’énergie.*Muesli/),
    ).toBeInTheDocument();
    expect(
      within(panel).queryByRole('button', { name: 'Utiliser ces repas' }),
    ).toBeNull();
  });

  it('says which products are used up apart from those with no energy value', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withProfile()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`POST ${PROPOSE_URL}`]: ok(
        proposal({
          skipped: [
            { barcode: MUESLI.barcode, name: 'Muesli', reason: 'no_energy' },
            { barcode: '3017620422003', name: 'Huile', reason: 'out_of_stock' },
            { barcode: '3017620422004', name: 'Lait', reason: 'out_of_stock' },
          ],
        }),
      ),
    });
    renderApp();

    fireEvent.click(
      await screen.findByRole('button', { name: /Compléter ma journée/ }),
    );

    const panel = await screen.findByRole('region', { name: 'Jour proposé' });
    expect(
      within(panel).getByText(/sans valeur d’énergie.*Muesli$/),
    ).toBeInTheDocument();
    expect(
      within(panel).getByText(/épuisés.*Huile, Lait$/),
    ).toBeInTheDocument();
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
      await screen.findByRole('button', { name: /Compléter ma journée/ }),
    );
    const panel = await screen.findByRole('region', { name: 'Jour proposé' });

    fireEvent.click(
      within(panel).getByRole('button', { name: 'Utiliser ces repas' }),
    );

    // The day shown is now the saved one, with rows to change, and the proposal is gone.
    expect(
      await screen.findByRole('button', { name: /^Pain de mie/ }),
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
      await screen.findByRole('button', { name: /Compléter ma journée/ }),
    );
    const panel = await screen.findByRole('region', { name: 'Jour proposé' });

    fireEvent.click(
      within(panel).getByRole('button', { name: 'Utiliser ces repas' }),
    );

    expect(confirm).toHaveBeenCalledWith(
      'Remplacer ce qui est dans les repas pas encore mangés ?',
    );
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
      await screen.findByRole('button', { name: /Compléter ma journée/ }),
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
      await screen.findByRole('button', { name: /Compléter ma journée/ }),
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
      await screen.findByRole('button', { name: /Compléter ma journée/ }),
    );
    await screen.findByRole('region', { name: 'Jour proposé' });

    fireEvent.click(screen.getByRole('button', { name: 'Jour suivant' }));

    // Once the next day is shown: while it loads, nothing is shown anyway.
    expect(await screen.findByLabelText('Jour')).toHaveValue('10/10/2026');
    await screen.findByRole('region', { name: 'Déjeuner' });
    expect(screen.queryByRole('region', { name: 'Jour proposé' })).toBeNull();
  });
});
