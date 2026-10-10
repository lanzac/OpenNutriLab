import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  BREAD,
  DAY_URL,
  MUESLI,
  breadItem,
  day,
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
  window.localStorage.clear();
});

const PROPOSE_URL = `${DAY_URL}/propose`;
const SUGGEST_URL = `${DAY_URL}/suggest`;
const LUNCH_URL = `${DAY_URL}/lunch`;
const BREAKFAST_URL = `${DAY_URL}/breakfast`;

const muesliItem = {
  ...breadItem,
  id: 9,
  barcode: MUESLI.barcode,
  name: 'Muesli',
  quantity: '60.00',
  unit: 'g',
  grams: '60.00',
  serving: null,
  package: MUESLI.package,
};

/** A day with a profile: the breakfast is eaten (muesli), a lunch of bread is not. */
const partlyEaten = () =>
  day({
    mass: '131.4',
    meals: [
      meal('breakfast', 'Petit-déjeuner', [muesliItem], {}, true),
      meal('lunch', 'Déjeuner', [breadItem]),
      meal('snack', 'Collation'),
      meal('dinner', 'Dîner'),
    ],
    nutrients: { energy: { name: 'Énergie', unit: 'kJ' } },
    needs: [],
    ratios: [],
  });

/** The same, as the server answers when the lunch is marked eaten too. */
const lunchEaten = () => {
  const found = partlyEaten();
  found.meals[1] = { ...found.meals[1], eaten: true };
  return found;
};

const switchOf = (label) => screen.getByRole('switch', { name: label });

describe('marking a meal as eaten', () => {
  it('has a switch on each meal, on for the meals that are eaten', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(partlyEaten()),
      'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
    });
    renderApp();

    await screen.findByRole('region', { name: 'Petit-déjeuner' });

    expect(switchOf('Mangé – Petit-déjeuner')).toBeChecked();
    for (const name of ['Déjeuner', 'Collation', 'Dîner']) {
      expect(switchOf(`Mangé – ${name}`)).not.toBeChecked();
    }
    // The help says what it is for.
    expect(screen.getByText(/Marquez les repas mangés/)).toBeInTheDocument();
  });

  it('shows a meal that is eaten apart from the others', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(partlyEaten()),
      'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
    });
    renderApp();

    const eaten = await screen.findByRole('region', {
      name: 'Petit-déjeuner',
    });
    const planned = screen.getByRole('region', { name: 'Déjeuner' });

    expect(eaten).toHaveClass('border-success');
    expect(planned).not.toHaveClass('border-success');
  });

  it('marks the meal through the server, with the token, and shows the day it answers', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(partlyEaten()),
      'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
      [`PATCH ${LUNCH_URL}`]: ok(lunchEaten()),
    });
    renderApp();
    await screen.findByRole('region', { name: 'Déjeuner' });

    fireEvent.click(switchOf('Mangé – Déjeuner'));

    await waitFor(() => expect(switchOf('Mangé – Déjeuner')).toBeChecked());
    expect(screen.getByRole('region', { name: 'Déjeuner' })).toHaveClass(
      'border-success',
    );
    const [, options] = fetch.mock.calls.find(([, o]) => o?.method === 'PATCH');
    expect(JSON.parse(options.body)).toEqual({ eaten: true });
    expect(options.headers['X-CSRFToken']).toBe('test-csrf-token');
  });

  it('flips the switch at once, without waiting for the day the server works out', async () => {
    let answer;
    stubFetch({
      [`GET ${DAY_URL}`]: ok(partlyEaten()),
      'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
      [`PATCH ${LUNCH_URL}`]: () =>
        new Promise((resolve) => {
          answer = resolve;
        }),
    });
    renderApp();
    await screen.findByRole('region', { name: 'Déjeuner' });

    fireEvent.click(switchOf('Mangé – Déjeuner'));

    // Asked, and not answered yet: the meal is shown eaten all the same.
    expect(switchOf('Mangé – Déjeuner')).toBeChecked();
    expect(screen.getByRole('region', { name: 'Déjeuner' })).toHaveClass(
      'border-success',
    );
    answer(ok(lunchEaten()));
    await waitFor(() => expect(switchOf('Mangé – Déjeuner')).toBeChecked());
  });

  it('marks a meal as not eaten again', async () => {
    const fetch = stubFetch({
      [`GET ${DAY_URL}`]: ok(partlyEaten()),
      'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
      [`PATCH ${BREAKFAST_URL}`]: ok(day()),
    });
    renderApp();
    await screen.findByRole('region', { name: 'Petit-déjeuner' });

    fireEvent.click(switchOf('Mangé – Petit-déjeuner'));

    await waitFor(() =>
      expect(switchOf('Mangé – Petit-déjeuner')).not.toBeChecked(),
    );
    const [, options] = fetch.mock.calls.find(([, o]) => o?.method === 'PATCH');
    expect(JSON.parse(options.body)).toEqual({ eaten: false });
  });

  it('says a meal eaten with nothing in it is a meal with nothing eaten', async () => {
    const skipped = day({
      meals: [
        meal('breakfast', 'Petit-déjeuner', [], {}, true),
        meal('lunch', 'Déjeuner'),
        meal('snack', 'Collation'),
        meal('dinner', 'Dîner'),
      ],
    });
    stubFetch({
      [`GET ${DAY_URL}`]: ok(skipped),
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    renderApp();

    const card = await screen.findByRole('region', { name: 'Petit-déjeuner' });

    expect(
      within(card).getByText('Rien mangé à ce repas.'),
    ).toBeInTheDocument();
    expect(screen.getAllByText('Rien dans ce repas.')).toHaveLength(3);
  });

  it('says so when the change could not be saved, and keeps the meal as it was', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    stubFetch({
      [`GET ${DAY_URL}`]: ok(partlyEaten()),
      'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
      [`PATCH ${LUNCH_URL}`]: { ok: false, status: 500 },
    });
    renderApp();
    await screen.findByRole('region', { name: 'Déjeuner' });

    fireEvent.click(switchOf('Mangé – Déjeuner'));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Le changement n’a pas pu être enregistré.',
    );
    expect(switchOf('Mangé – Déjeuner')).not.toBeChecked();
  });
});

// A day with a profile, so that there is something to propose it for.
const proposedDay = () => {
  const found = partlyEaten();
  found.meals[1] = {
    ...found.meals[1],
    items: [{ ...breadItem, id: null }],
  };
  found.meals[3] = {
    ...found.meals[3],
    items: [{ ...breadItem, id: null, barcode: '1', name: 'Compote' }],
  };
  return found;
};

const proposal = (overrides = {}) => ({
  status: 'optimal',
  objective: 1.5,
  items: [
    {
      kind: 'lunch',
      barcode: BREAD.barcode,
      quantity: '2.00',
      unit: 'serving',
    },
  ],
  skipped: [],
  day: proposedDay(),
  ...overrides,
});

async function openProposal(found = partlyEaten(), body = proposal()) {
  const fetch = stubFetch({
    [`GET ${DAY_URL}`]: ok(found),
    'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
    [`POST ${PROPOSE_URL}`]: ok(body),
    [`PATCH ${LUNCH_URL}`]: ok(lunchEaten()),
    [`PUT ${DAY_URL}`]: ok(partlyEaten()),
  });
  renderApp();
  fireEvent.click(
    await screen.findByRole('button', { name: /Proposer un jour/ }),
  );
  const panel = await screen.findByRole('region', { name: 'Jour proposé' });
  return { fetch, panel };
}

describe('a day proposed on top of the meals eaten', () => {
  it('shows the meals eaten as eaten and the others as what to add, read only', async () => {
    const { panel } = await openProposal();

    const breakfast = within(panel).getByRole('region', {
      name: 'Petit-déjeuner',
    });
    const lunch = within(panel).getByRole('region', { name: 'Déjeuner' });
    const snack = within(panel).getByRole('region', { name: 'Collation' });

    expect(within(breakfast).getByText('Mangé')).toBeInTheDocument();
    expect(within(breakfast).getByText('Muesli')).toBeInTheDocument();
    expect(within(lunch).getByText('À ajouter')).toBeInTheDocument();
    expect(within(lunch).getByText('Pain de mie')).toBeInTheDocument();
    // A meal with nothing in it has no badge, and nothing can be changed here.
    expect(within(snack).queryByText('À ajouter')).toBeNull();
    expect(within(panel).queryByRole('switch')).toBeNull();
    expect(within(panel).queryByRole('spinbutton')).toBeNull();
  });

  it('takes the proposal without asking when only meals eaten have something in them', async () => {
    const onlyEaten = day({
      meals: [
        meal('breakfast', 'Petit-déjeuner', [muesliItem], {}, true),
        meal('lunch', 'Déjeuner'),
        meal('snack', 'Collation'),
        meal('dinner', 'Dîner'),
      ],
      needs: [],
      ratios: [],
    });
    const confirm = vi.fn();
    vi.stubGlobal('confirm', confirm);
    const { fetch, panel } = await openProposal(onlyEaten);

    fireEvent.click(
      within(panel).getByRole('button', { name: 'Utiliser ce jour' }),
    );

    await waitFor(() =>
      expect(screen.queryByRole('region', { name: 'Jour proposé' })).toBeNull(),
    );
    expect(confirm).not.toHaveBeenCalled();
    expect(fetch.mock.calls.some(([, o]) => o?.method === 'PUT')).toBe(true);
  });

  it('asks before it replaces a meal that is not eaten and has something in it', async () => {
    const confirm = vi.fn().mockReturnValue(false);
    vi.stubGlobal('confirm', confirm);
    const { fetch, panel } = await openProposal();

    fireEvent.click(
      within(panel).getByRole('button', { name: 'Utiliser ce jour' }),
    );

    // The lunch of bread is not eaten: it is what goes.
    expect(confirm).toHaveBeenCalledWith(
      'Remplacer ce qui est dans les repas pas encore mangés ?',
    );
    expect(fetch.mock.calls.some(([, o]) => o?.method === 'PUT')).toBe(false);
  });

  it('is out of date once a meal is marked eaten, and is closed', async () => {
    await openProposal();

    fireEvent.click(switchOf('Mangé – Déjeuner'));

    await waitFor(() =>
      expect(screen.queryByRole('region', { name: 'Jour proposé' })).toBeNull(),
    );
    expect(switchOf('Mangé – Déjeuner')).toBeChecked();
  });

  it('is out of date once a meal that is eaten is changed, and not for a meal that is not', async () => {
    const changed = partlyEaten();
    changed.meals[0] = {
      ...changed.meals[0],
      items: [{ ...muesliItem, quantity: '80.00', grams: '80.00' }],
    };
    const { fetch, panel } = await openProposal();
    // The meals of the page itself, and not the proposal's copies of them.
    const onPage = (name) =>
      screen
        .getAllByRole('region', { name })
        .find((card) => !panel.contains(card));
    fetch.mockImplementation(async (url, options = {}) => {
      const key = `${options.method ?? 'GET'} ${url}`;
      if (key === 'PATCH /api/v1/meals/items/7') return ok(partlyEaten());
      if (key === 'PATCH /api/v1/meals/items/9') return ok(changed);
      throw new Error(`unexpected request: ${key}`);
    });

    // The bread is in the lunch, which is not eaten: the proposal is for the same day.
    const bread = within(onPage('Déjeuner')).getByLabelText(
      'Quantité – Pain de mie',
    );
    fireEvent.change(bread, { target: { value: '3' } });
    fireEvent.blur(bread);
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(([u]) => u === '/api/v1/meals/items/7'),
      ).toBe(true),
    );
    expect(
      screen.getByRole('region', { name: 'Jour proposé' }),
    ).toBeInTheDocument();

    // The muesli is in the breakfast, which is eaten: the proposal counted it.
    const input = within(onPage('Petit-déjeuner')).getByLabelText(
      'Quantité – Muesli',
    );
    fireEvent.change(input, { target: { value: '80' } });
    fireEvent.blur(input);

    await waitFor(() =>
      expect(screen.queryByRole('region', { name: 'Jour proposé' })).toBeNull(),
    );
  });

  it('says every meal is eaten when there is nothing to fill, and offers nothing to take', async () => {
    const { panel } = await openProposal(
      partlyEaten(),
      proposal({ status: 'nothing_to_fill', items: [] }),
    );

    expect(
      within(panel).getByText(
        'Tous les repas du jour sont mangés : rien à ajouter.',
      ),
    ).toBeInTheDocument();
    expect(
      within(panel).queryByRole('button', { name: 'Utiliser ce jour' }),
    ).toBeNull();
  });

  it('says there is nothing to add when the meals eaten bring what the day needs', async () => {
    const { panel } = await openProposal(
      partlyEaten(),
      proposal({ status: 'optimal', items: [] }),
    );

    expect(
      within(panel).getByText(
        'Rien à ajouter : les repas mangés apportent ce dont la journée a besoin.',
      ),
    ).toBeInTheDocument();
    expect(
      within(panel).queryByText('Le meilleur jour que permet l’inventaire.'),
    ).toBeNull();
  });
});

describe('foods suggested on top of the meals eaten', () => {
  it('says there is nothing to suggest when every meal is eaten', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(partlyEaten()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`POST ${SUGGEST_URL}`]: ok({
        status: 'nothing_to_fill',
        missed_before: 3,
        missed_after: 3,
        total: 42,
        foods: [],
        day: partlyEaten(),
      }),
    });
    renderApp();

    fireEvent.click(
      await screen.findByRole('button', { name: /Suggérer des aliments/ }),
    );

    expect(
      await screen.findByText(
        'Tous les repas du jour sont mangés : rien à suggérer.',
      ),
    ).toBeInTheDocument();
  });

  it('is out of date once a meal is marked eaten, and is closed', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(partlyEaten()),
      'GET /api/v1/inventory/': ok([BREAD]),
      [`POST ${SUGGEST_URL}`]: ok({
        status: 'no_gaps',
        missed_before: 0,
        missed_after: 0,
        total: 42,
        foods: [],
        day: partlyEaten(),
      }),
      [`PATCH ${LUNCH_URL}`]: ok(lunchEaten()),
    });
    renderApp();
    fireEvent.click(
      await screen.findByRole('button', { name: /Suggérer des aliments/ }),
    );
    await screen.findByRole('region', { name: 'Aliments à se procurer' });

    fireEvent.click(switchOf('Mangé – Déjeuner'));

    await waitFor(() =>
      expect(
        screen.queryByRole('region', { name: 'Aliments à se procurer' }),
      ).toBeNull(),
    );
  });
});

// ---------------------------------------------------------------------------
// What the day says of what was eaten
// ---------------------------------------------------------------------------
const withEatenNeeds = (eatenMeals = true) => {
  const found = withBread({
    needs: [
      need({
        name: 'Fibres',
        total: total('12', '10', '14'),
        eaten: eatenMeals ? '8' : null,
      }),
      need({
        name: 'Fer',
        unit: 'mg',
        group: 'mineral',
        group_label: 'Minéral',
        low: '11',
        total: total('12.5', '12', '13'),
        eaten: eatenMeals ? '0' : null,
        status: 'within',
      }),
    ],
    ratios: [ratio({})],
  });
  found.meals[0] = { ...found.meals[0], eaten: eatenMeals };
  return found;
};

async function summaryOf(found) {
  stubFetch({
    [`GET ${DAY_URL}`]: ok(found),
    'GET /api/v1/inventory/': ok([BREAD]),
  });
  renderApp();
  return screen.findByRole('region', { name: 'La journée face à vos besoins' });
}

describe('the day against the needs, with what was eaten', () => {
  it('draws the part eaten as the darker part of the bar, and says how much', async () => {
    const region = await summaryOf(withEatenNeeds());

    const fibre = within(region).getByRole('meter', { name: 'Fibres' });
    const eaten = fibre.querySelector('.gauge-eaten');
    expect(eaten).not.toBeNull();
    // 8 g of the 12 g: two thirds of the bar.
    const fill = fibre.querySelector('.gauge-fill');
    expect(parseFloat(eaten.style.width)).toBeCloseTo(
      (parseFloat(fill.style.width) * 8) / 12,
      3,
    );
    expect(
      within(fibre.parentElement).getByText(/dont mangé 8 g/),
    ).toBeInTheDocument();
    expect(fibre.getAttribute('aria-valuetext')).toMatch(/dont mangé 8 g$/);
  });

  it('draws nothing for a need nothing of which was eaten', async () => {
    const region = await summaryOf(withEatenNeeds());

    const iron = within(region).getByRole('meter', { name: 'Fer' });

    expect(iron.querySelector('.gauge-eaten')).toBeNull();
    expect(within(iron.parentElement).queryByText(/dont mangé/)).toBeNull();
  });

  it('draws nothing at all when no meal is eaten', async () => {
    const region = await summaryOf(withEatenNeeds(false));

    expect(region.querySelector('.gauge-eaten')).toBeNull();
    expect(within(region).queryByText(/dont mangé/)).toBeNull();
    expect(within(region).queryByText('Plus foncé : déjà mangé')).toBeNull();
  });

  it('explains the darker part in the legend, once a meal is eaten', async () => {
    const region = await summaryOf(withEatenNeeds());

    expect(
      within(region).getByText('Plus foncé : déjà mangé'),
    ).toBeInTheDocument();
  });

  it('has a column for what was eaten in the table, once a meal is', async () => {
    const region = await summaryOf(withEatenNeeds());
    fireEvent.click(within(region).getByRole('button', { name: 'Tableau' }));

    const table = within(region).getAllByRole('table')[0];

    const headers = within(table)
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent);
    expect(headers).toContain('Mangé');
    const fibre = within(table).getByText('Fibres').closest('tr');
    expect(within(fibre).getAllByRole('cell')[2]).toHaveTextContent('8 g');
  });

  it('has no such column when no meal is eaten', async () => {
    const region = await summaryOf(withEatenNeeds(false));
    fireEvent.click(within(region).getByRole('button', { name: 'Tableau' }));

    const table = within(region).getAllByRole('table')[0];

    expect(
      within(table)
        .getAllByRole('columnheader')
        .map((cell) => cell.textContent),
    ).not.toContain('Mangé');
  });
});
