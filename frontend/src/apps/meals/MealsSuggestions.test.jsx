import { fireEvent, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  BREAD,
  DAY_URL,
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

const SUGGEST_URL = `${DAY_URL}/suggest`;

// A day with a profile, so that there is something to suggest for.
const withProfile = () => ({ ...day(), needs: [], ratios: [] });

// The day the suggested foods make: bread, and a food that is not a product.
const suggestedDay = () => {
  const found = withBread({
    needs: [need({ status: 'within', certain: true })],
    ratios: [ratio({ status: 'within', certain: true })],
  });
  found.meals[1].items = [
    {
      id: null,
      barcode: 'ciqual:26141',
      name: 'Foie de morue',
      quantity: '60.00',
      unit: 'g',
      grams: '60.00',
      serving: null,
      generic: true,
      url: 'https://ciqual.anses.fr/#/aliments/26141',
    },
  ];
  found.mass = '131.4';
  return found;
};

const oil = {
  code: '17180',
  name: 'Huile de lin',
  group: 'matières grasses',
  url: 'https://ciqual.anses.fr/#/aliments/17180',
  grams: '20.00',
  meals: [{ kind: 'dinner', label: 'Dîner', grams: '20.00' }],
  helps: [
    {
      name: 'Alpha-linolénique',
      unit: 'g',
      amount: '10.68',
      share: '3.62',
      raised: '',
    },
    {
      name: 'Oméga-3 / Oméga-6',
      unit: 'g',
      amount: '10.68',
      share: '0.45',
      raised: 'Oméga-3',
    },
  ],
};

const suggestions = (overrides = {}) => ({
  status: 'optimal',
  missed_before: 18,
  missed_after: 4,
  total: 42,
  foods: [oil],
  day: suggestedDay(),
  ...overrides,
});

describe('suggesting foods', () => {
  it('cannot be asked for without a profile', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(day()),
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    renderApp();

    const button = await screen.findByRole('button', {
      name: /Quoi acheter/,
    });

    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('title', 'Renseignez votre profil.');
  });

  it('shows the foods, how much and where, what they close and how much of it', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(withProfile()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`POST ${SUGGEST_URL}`]: ok(suggestions()),
    });
    renderApp();

    fireEvent.click(
      await screen.findByRole('button', { name: /Quoi acheter/ }),
    );

    const panel = await screen.findByRole('region', {
      name: 'Aliments à se procurer',
    });
    // The count of what is missed, from the server's words with the figures put in.
    expect(
      within(panel).getByText(
        'Avec ces aliments, 4 besoins sur 42 ne sont pas couverts, contre 18 sans.',
      ),
    ).toBeInTheDocument();
    const link = within(panel).getByRole('link', { name: 'Huile de lin' });
    expect(link).toHaveAttribute(
      'href',
      'https://ciqual.anses.fr/#/aliments/17180',
    );
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(within(panel).getByText('20 g · Dîner')).toBeInTheDocument();
    expect(within(panel).getByText('matières grasses')).toBeInTheDocument();
    // What it closes: more than the need is said so, less is a share, and a ratio
    // names what is raised and the ratio.
    expect(
      within(panel).getByText(/Alpha-linolénique \+10,7 g/),
    ).toBeInTheDocument();
    expect(within(panel).getByText(/couvre le besoin/)).toBeInTheDocument();
    expect(within(panel).getByText(/Oméga-3 \+10,7 g/)).toBeInTheDocument();
    expect(
      within(panel).getByText(/Rapport Oméga-3 \/ Oméga-6/),
    ).toBeInTheDocument();
    expect(within(panel).getByText(/45\s%\sdu besoin/)).toBeInTheDocument();
    // The caution that goes with it, and nothing written.
    expect(
      within(panel).getByText(/contrôlez-la avant d’agir/),
    ).toBeInTheDocument();
    const posts = fetch.mock.calls.filter(([, o]) => o?.method === 'POST');
    expect(posts).toHaveLength(1);
    expect(posts[0][1].headers['X-CSRFToken']).toBe('test-csrf-token');
    expect(fetch.mock.calls.some(([, o]) => o?.method === 'PUT')).toBe(false);
  });

  it('shows the day they make, with the foods that are not products badged', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withProfile()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`POST ${SUGGEST_URL}`]: ok(suggestions()),
    });
    renderApp();
    fireEvent.click(
      await screen.findByRole('button', { name: /Quoi acheter/ }),
    );
    const panel = await screen.findByRole('region', {
      name: 'Aliments à se procurer',
    });

    const details = within(panel)
      .getByText('Voir la journée avec ces aliments')
      .closest('details');

    // The meals read only: a product, and a food that is not one, linked to its sheet.
    expect(within(details).getByText('Foie de morue')).toBeInTheDocument();
    const badge = within(details).getByRole('link', { name: 'suggéré' });
    expect(badge).toHaveAttribute(
      'href',
      'https://ciqual.anses.fr/#/aliments/26141',
    );
    expect(within(details).queryByRole('spinbutton')).toBeNull();
    expect(
      within(details).getByRole('region', {
        name: 'La journée face à vos besoins',
      }),
    ).toBeInTheDocument();
  });

  it('says it is looking while it looks', async () => {
    let answer;
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withProfile()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`POST ${SUGGEST_URL}`]: () =>
        new Promise((resolve) => {
          answer = resolve;
        }),
    });
    renderApp();

    fireEvent.click(
      await screen.findByRole('button', { name: /Quoi acheter/ }),
    );

    const looking = await screen.findByRole('button', {
      name: /Recherche d’aliments/,
    });
    expect(looking).toBeDisabled();
    answer(ok(suggestions()));
    expect(
      await screen.findByRole('region', { name: 'Aliments à se procurer' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Quoi acheter/ })).toBeEnabled();
  });

  it.each([
    ['no_gaps', 'Votre inventaire ne manque de rien.'],
    ['no_foods', 'Aucun aliment de la table ne comble ce qui manque.'],
    ['no_suggestion', 'Aucun aliment ne vaut la peine de ce qui manque.'],
    ['failed', 'Aucun jour n’a pu être calculé.'],
  ])(
    'says why when the status is %s, with no food and no day',
    async (status, said) => {
      stubFetch({
        [`GET ${DAY_URL}`]: ok(withProfile()),
        'GET /api/v1/inventory/': ok([BREAD]),
        [`POST ${SUGGEST_URL}`]: ok(suggestions({ status, foods: [] })),
      });
      renderApp();

      fireEvent.click(
        await screen.findByRole('button', { name: /Quoi acheter/ }),
      );

      const panel = await screen.findByRole('region', {
        name: 'Aliments à se procurer',
      });
      expect(within(panel).getByText(said)).toBeInTheDocument();
      expect(within(panel).queryByText(/contrôlez-la/)).toBeNull();
      expect(
        within(panel).queryByText('Voir la journée avec ces aliments'),
      ).toBeNull();
    },
  );

  it('says so when no food could be suggested', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withProfile()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`POST ${SUGGEST_URL}`]: { ok: false, status: 422 },
    });
    renderApp();

    fireEvent.click(
      await screen.findByRole('button', { name: /Quoi acheter/ }),
    );

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Aucun aliment n’a pu être suggéré.',
    );
    expect(
      screen.queryByRole('region', { name: 'Aliments à se procurer' }),
    ).toBeNull();
  });

  it('is closed on request, and dropped when the day changes', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withProfile()),
      'GET /api/v1/meals/2026-10-10': ok({
        ...withProfile(),
        day: '2026-10-10',
      }),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`POST ${SUGGEST_URL}`]: ok(suggestions()),
    });
    renderApp();
    fireEvent.click(
      await screen.findByRole('button', { name: /Quoi acheter/ }),
    );
    const panel = await screen.findByRole('region', {
      name: 'Aliments à se procurer',
    });

    fireEvent.click(within(panel).getByRole('button', { name: 'Fermer' }));
    expect(
      screen.queryByRole('region', { name: 'Aliments à se procurer' }),
    ).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /Quoi acheter/ }));
    await screen.findByRole('region', { name: 'Aliments à se procurer' });
    fireEvent.click(screen.getByRole('button', { name: 'Jour suivant' }));

    // Once the next day is shown: while it loads, nothing is shown anyway.
    expect(await screen.findByLabelText('Jour')).toHaveValue('10/10/2026');
    await screen.findByRole('region', { name: 'Déjeuner' });
    expect(
      screen.queryByRole('region', { name: 'Aliments à se procurer' }),
    ).toBeNull();
  });
});
