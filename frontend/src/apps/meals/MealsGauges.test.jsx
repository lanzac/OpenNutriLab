import { fireEvent, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  BREAD,
  DAY_URL,
  MUESLI,
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
  window.localStorage.clear();
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
      need({
        name: 'Fer',
        unit: 'mg',
        group: 'mineral',
        group_label: 'Minéral',
        low: '11',
        high: null,
        total: total('12.5', '12', '13', '100'),
        status: 'within',
        certain: true,
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

async function summary({ openGroups = true } = {}) {
  stubFetch({
    [`GET ${DAY_URL}`]: ok(withNeeds()),
    'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
  });
  renderApp({ openGroups });
  return screen.findByRole('region', { name: 'La journée face à vos besoins' });
}

describe('the day as gauges', () => {
  it('shows a gauge for each need and each ratio, and no table, by default', async () => {
    const region = await summary();

    for (const name of [
      'Fibres',
      'Énergie',
      'Sodium',
      'Fer',
      'Oméga-3 / Oméga-6',
      'Sodium / Oméga-6 (en moles)',
    ]) {
      expect(within(region).getByRole('meter', { name })).toBeInTheDocument();
    }
    expect(within(region).queryByRole('table')).toBeNull();
    expect(
      within(region).getByRole('button', { name: 'Jauges' }),
    ).toHaveAttribute('aria-pressed', 'true');
  });

  it('draws the amount against what is wanted, with its verdict as the colour', async () => {
    const region = await summary();

    const fibre = within(region).getByRole('meter', { name: 'Fibres' });
    // 12 g of the 30 g wanted at least: the scale is 30 x 1.6.
    expect(fibre).toHaveAttribute('aria-valuenow', '12');
    expect(fibre).toHaveAttribute('aria-valuemax', '48');
    expect(fibre.querySelector('.gauge-fill--below')).not.toBeNull();
    expect(fibre.querySelector('.gauge-fill--uncertain')).toBeNull();
    expect(fibre.getAttribute('aria-valuetext')).toMatch(/12 g, 40\s%, Sous$/);
    const iron = within(region).getByRole('meter', { name: 'Fer' });
    expect(iron.querySelector('.gauge-fill--within')).not.toBeNull();
  });

  it('shows what is wanted as a zone and a tick for each end, with their values', async () => {
    const region = await summary();

    const sodium = within(region).getByRole('meter', { name: 'Sodium' });
    expect(sodium.querySelector('.gauge-zone')).not.toBeNull();
    expect(sodium.querySelectorAll('.gauge-tick')).toHaveLength(2);
    expect(within(sodium).getByText('≥ 1 500 mg')).toBeInTheDocument();
    expect(within(sodium).getByText('≤ 2 300 mg')).toBeInTheDocument();
    // One tick when only an end is wanted.
    const fibre = within(region).getByRole('meter', { name: 'Fibres' });
    expect(fibre.querySelectorAll('.gauge-tick')).toHaveLength(1);
    expect(within(fibre).getByText('≥ 30 g')).toBeInTheDocument();
  });

  it('shows the range the amount can be in, open at the end when it has no upper end', async () => {
    const region = await summary();

    const fibre = within(region).getByRole('meter', { name: 'Fibres' });
    expect(fibre.querySelector('.gauge-interval')).not.toBeNull();
    expect(fibre.querySelector('.gauge-interval--open')).toBeNull();
    expect(fibre.getAttribute('title')).toMatch(/10\s–\s14/);
    const sodium = within(region).getByRole('meter', { name: 'Sodium' });
    expect(sodium.querySelector('.gauge-interval--open')).not.toBeNull();
    expect(sodium.getAttribute('title')).toMatch(/1\s500\s–\s\?/);
  });

  it('hatches a verdict the range does not bear out, and says what is not covered', async () => {
    const region = await summary();

    const sodium = within(region).getByRole('meter', { name: 'Sodium' });
    expect(sodium.querySelector('.gauge-fill--uncertain')).not.toBeNull();
    expect(sodium.getAttribute('aria-valuetext')).toMatch(/Atteint \?$/);
    const row = sodium.closest('.gauge-row');
    expect(within(row).getByText('Couverture 60 %')).toBeInTheDocument();
    expect(within(row).getByText('1 800 mg')).toBeInTheDocument();
    expect(within(row).getByText(/120\s%\s\?/)).toBeInTheDocument();
    // What is covered whole says nothing of it.
    const fibre = within(region)
      .getByRole('meter', { name: 'Fibres' })
      .closest('.gauge-row');
    expect(within(fibre).queryByText(/Couverture/)).toBeNull();
  });

  it('writes the energy in kcal, as everywhere', async () => {
    const region = await summary();

    const energy = within(region).getByRole('meter', { name: 'Énergie' });
    const row = energy.closest('.gauge-row');
    expect(within(row).getByText('900 kcal')).toBeInTheDocument();
    // The two ends are close on the track: one label serves both.
    expect(
      within(energy).getByText(/2\s518\skcal\s–\s2\s783\skcal/),
    ).toBeInTheDocument();
  });

  it('gives a ratio over nothing no amount and the colour of what is not known', async () => {
    const region = await summary();

    const unknown = within(region).getByRole('meter', {
      name: 'Sodium / Oméga-6 (en moles)',
    });
    expect(unknown.querySelector('.gauge-fill--unknown')).not.toBeNull();
    expect(unknown).toHaveAttribute('aria-valuenow', '0');
    const omega = within(region).getByRole('meter', {
      name: 'Oméga-3 / Oméga-6',
    });
    expect(within(omega).getByText('0,9 – 1,1')).toBeInTheDocument();
  });

  it('sums the day up in one bar with how many are met, short and over', async () => {
    const region = await summary();

    // Fibre, energy and the omega ratio are short; sodium and iron are met; one
    // ratio is not known.
    const bar = within(region).getByRole('img', { name: '2 / 6 Atteint' });
    expect(bar.querySelectorAll('[class^="status-bar-part"]')).toHaveLength(3);
    expect(within(region).getByText('Sous 3')).toBeInTheDocument();
    expect(within(region).getByText('Atteint 2')).toBeInTheDocument();
    expect(within(region).getByText('Inconnu 1')).toBeInTheDocument();
    expect(within(region).queryByText(/Au-dessus \d/)).toBeNull();
  });
});

describe('the choice between the gauges and the table', () => {
  it('shows the table with every figure when it is chosen', async () => {
    const region = await summary();

    fireEvent.click(within(region).getByRole('button', { name: 'Tableau' }));

    expect(within(region).getAllByRole('table').length).toBeGreaterThan(0);
    expect(within(region).queryByRole('meter')).toBeNull();
    expect(
      within(region).getByRole('row', { name: /Fibres/ }),
    ).toBeInTheDocument();
    expect(
      within(region).getByRole('button', { name: 'Tableau' }),
    ).toHaveAttribute('aria-pressed', 'true');
    // The bar that sums the day up stays.
    expect(
      within(region).getByRole('img', { name: '2 / 6 Atteint' }),
    ).toBeInTheDocument();
  });

  it('goes back to the gauges', async () => {
    const region = await summary();
    fireEvent.click(within(region).getByRole('button', { name: 'Tableau' }));

    fireEvent.click(within(region).getByRole('button', { name: 'Jauges' }));

    expect(within(region).getAllByRole('meter').length).toBeGreaterThan(0);
    expect(within(region).queryByRole('table')).toBeNull();
  });

  it('is kept for the next visit', async () => {
    const first = await summary();
    fireEvent.click(within(first).getByRole('button', { name: 'Tableau' }));
    expect(window.localStorage.getItem('meals.summaryMode')).toBe('table');
    document.body.innerHTML = '';

    const second = await summary();

    expect(within(second).getAllByRole('table').length).toBeGreaterThan(0);
    expect(within(second).queryByRole('meter')).toBeNull();
  });

  it('shows the gauges when what was kept is not a mode', async () => {
    window.localStorage.setItem('meals.summaryMode', 'nonsense');

    const region = await summary();

    expect(within(region).getAllByRole('meter').length).toBeGreaterThan(0);
  });

  it('works without storage, which a private window can refuse', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const region = await summary();
    // The groups are closed, as nothing says otherwise.
    fireEvent.click(
      within(region).getByRole('button', { name: 'Tout déplier' }),
    );
    expect(within(region).getAllByRole('meter').length).toBeGreaterThan(0);

    fireEvent.click(within(region).getByRole('button', { name: 'Tableau' }));

    expect(within(region).queryByRole('meter')).toBeNull();
    expect(
      within(region).getByRole('row', { name: /Fibres/ }),
    ).toBeInTheDocument();
  });
});

describe('the total quantity of a product', () => {
  it('is in the choice of a product, and what an item is of a package', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withNeeds()),
      'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
    });
    renderApp();

    const breakfast = await screen.findByRole('region', {
      name: 'Petit-déjeuner',
    });

    // 71.4 g of a package of 500 g, where the item opens.
    await openItem('Pain de mie', within(breakfast));
    expect(
      within(breakfast).getByText(/14\s%\sd’un paquet de 500 g/),
    ).toBeInTheDocument();
    // What a package holds, with the product in the window.
    const dialog = await openPicker('Petit-déjeuner');
    expect(
      within(dialog).getByRole('button', { name: /^Muesli/ }),
    ).toHaveTextContent('375 g');
  });

  it('is a share of what the package weighs, which a density gives for a volume', async () => {
    // 100 g of an oil of which the package is 1000 ml: it weighs 911.5 g.
    const found = withNeeds();
    found.meals[0].items[0] = {
      ...found.meals[0].items[0],
      grams: '91.15',
      package: { quantity: '1000.00', unit: 'ml' },
      package_grams: '911.50',
    };
    stubFetch({
      [`GET ${DAY_URL}`]: ok(found),
      'GET /api/v1/inventory/': ok([BREAD]),
    });
    renderApp();

    const breakfast = await screen.findByRole('region', {
      name: 'Petit-déjeuner',
    });

    // 91.15 of 911.5, a tenth, where 1000 would have made it 9 %.
    await openItem('Pain de mie', within(breakfast));
    expect(
      within(breakfast).getByText(/10\s%\sd’un paquet de 1\s?000 ml/),
    ).toBeInTheDocument();
  });

  it('is said in the limits of each product', async () => {
    stubFetch({
      [`GET ${DAY_URL}`]: ok(withNeeds()),
      'GET /api/v1/inventory/': ok([BREAD, MUESLI]),
    });
    renderApp();
    const summaryText = await screen.findByText('Limites pour le jour proposé');
    const limits = summaryText.closest('details');

    const bread = await within(limits).findByText('Pain de mie');

    expect(bread.closest('td')).toHaveTextContent('Quantité totale : 500 g');
  });

  it('says nothing of a package a product does not have', async () => {
    const found = withNeeds();
    found.meals[0].items[0].package = null;
    stubFetch({
      [`GET ${DAY_URL}`]: ok(found),
      'GET /api/v1/inventory/': ok([{ ...MUESLI, package: null }]),
    });
    renderApp();

    const breakfast = await screen.findByRole('region', {
      name: 'Petit-déjeuner',
    });

    await openItem('Pain de mie', within(breakfast));
    expect(within(breakfast).queryByText(/d’un paquet/)).toBeNull();
    const dialog = await openPicker('Petit-déjeuner');
    expect(
      within(dialog).getByRole('button', { name: /^Muesli/ }),
    ).toHaveTextContent(/^Muesli$/);
  });
});

describe('the groups of the day, closed at first', () => {
  const group = (region, name) =>
    within(region).getByRole('button', { name: new RegExp(name) });
  const closed = () => summary({ openGroups: false });
  const names = ['Énergie', 'Macronutriment', 'Minéral', 'Rapports'];

  it('shows every group closed, each with how many of its needs are met', async () => {
    const region = await closed();

    for (const name of names) {
      expect(group(region, name)).toHaveAttribute('aria-expanded', 'false');
    }
    expect(within(region).queryByRole('meter')).toBeNull();
    // Sodium and iron are both met; the omega ratio is short, the other unknown.
    expect(group(region, 'Minéral')).toHaveTextContent('2 sur 2 respectés');
    expect(group(region, 'Rapports')).toHaveTextContent('0 sur 2 respectés');
    expect(group(region, 'Macronutriment')).toHaveTextContent(
      '0 sur 1 respectés',
    );
    // And the whole day is still said in one bar.
    expect(
      within(region).getByRole('img', { name: '2 / 6 Atteint' }),
    ).toBeInTheDocument();
  });

  it('shows the gauges of a group that is opened, and only those', async () => {
    const region = await closed();

    fireEvent.click(group(region, 'Minéral'));

    expect(group(region, 'Minéral')).toHaveAttribute('aria-expanded', 'true');
    expect(
      within(region).getByRole('meter', { name: 'Sodium' }),
    ).toBeInTheDocument();
    expect(
      within(region).getByRole('meter', { name: 'Fer' }),
    ).toBeInTheDocument();
    expect(within(region).queryByRole('meter', { name: 'Fibres' })).toBeNull();
    // What an open group holds is still said, at its head.
    expect(group(region, 'Minéral')).toHaveTextContent('2 sur 2 respectés');
  });

  it('closes a group again', async () => {
    const region = await closed();
    fireEvent.click(group(region, 'Minéral'));

    fireEvent.click(group(region, 'Minéral'));

    expect(group(region, 'Minéral')).toHaveAttribute('aria-expanded', 'false');
    expect(within(region).queryByRole('meter', { name: 'Sodium' })).toBeNull();
  });

  it('opens the ratios as a group of their own', async () => {
    const region = await closed();

    fireEvent.click(group(region, 'Rapports'));

    expect(
      within(region).getByRole('meter', { name: 'Oméga-3 / Oméga-6' }),
    ).toBeInTheDocument();
    expect(within(region).queryByRole('meter', { name: 'Sodium' })).toBeNull();
  });

  it('unfolds and folds all of them at once', async () => {
    const region = await closed();

    fireEvent.click(
      within(region).getByRole('button', { name: 'Tout déplier' }),
    );

    expect(within(region).getAllByRole('meter')).toHaveLength(6);
    for (const name of names) {
      expect(group(region, name)).toHaveAttribute('aria-expanded', 'true');
    }
    expect(
      within(region).queryByRole('button', { name: 'Tout déplier' }),
    ).toBeNull();

    fireEvent.click(
      within(region).getByRole('button', { name: 'Tout replier' }),
    );

    expect(within(region).queryByRole('meter')).toBeNull();
  });

  it('offers to fold all once a group is open', async () => {
    const region = await closed();

    fireEvent.click(group(region, 'Minéral'));

    expect(
      within(region).getByRole('button', { name: 'Tout replier' }),
    ).toBeInTheDocument();
    expect(within(region).getAllByRole('meter')).toHaveLength(2);
  });

  it('keeps what is open for the next visit', async () => {
    const first = await closed();
    fireEvent.click(group(first, 'Minéral'));
    expect(window.localStorage.getItem('meals.openGroups')).toBe('["mineral"]');
    document.body.innerHTML = '';

    const second = await closed();

    expect(group(second, 'Minéral')).toHaveAttribute('aria-expanded', 'true');
    expect(
      within(second).getByRole('meter', { name: 'Sodium' }),
    ).toBeInTheDocument();
    expect(within(second).queryByRole('meter', { name: 'Fibres' })).toBeNull();
  });

  it('keeps everything closed when what was kept is not a list of groups', async () => {
    window.localStorage.setItem('meals.openGroups', '{"mineral": true}');

    const region = await closed();

    expect(within(region).queryByRole('meter')).toBeNull();
  });

  it('works without storage', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const region = await closed();
    expect(within(region).queryByRole('meter')).toBeNull();

    fireEvent.click(group(region, 'Minéral'));

    expect(
      within(region).getByRole('meter', { name: 'Sodium' }),
    ).toBeInTheDocument();
  });

  it('opens the same groups in the table', async () => {
    const region = await closed();
    fireEvent.click(within(region).getByRole('button', { name: 'Tableau' }));
    expect(
      within(region).queryByRole('row', { name: /^Sodium\s\d/ }),
    ).toBeNull();

    fireEvent.click(group(region, 'Minéral'));

    expect(
      within(region).getByRole('row', { name: /^Sodium\s\d/ }),
    ).toBeInTheDocument();
    expect(within(region).queryByRole('row', { name: /Fibres/ })).toBeNull();
    expect(group(region, 'Minéral')).toHaveAttribute('aria-expanded', 'true');
  });

  it('opens the table of the ratios', async () => {
    const region = await closed();
    fireEvent.click(within(region).getByRole('button', { name: 'Tableau' }));
    // The needs' table, whose groups are closed, and no table of the ratios.
    expect(within(region).getAllByRole('table')).toHaveLength(1);

    fireEvent.click(group(region, 'Rapports'));

    expect(within(region).getAllByRole('table')).toHaveLength(2);
  });
});
