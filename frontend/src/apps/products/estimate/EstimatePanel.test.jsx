import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { EstimatePanel } from './EstimatePanel.jsx';

// What the server hands over (see estimate_panel.py), with its labels as translated.
const labels = {
  view: 'Affichage',
  viewGauges: 'Jauges',
  viewTable: 'Tableau',
  collapseAll: 'Tout replier',
  expandAll: 'Tout déplier',
  legendEstimate: 'Estimation et sa fourchette',
  legendLabel: 'Étiquette (valeur et arrondi)',
  legendOpen: 'Pointillé : aucun maximum n’est connu.',
  ingredients: 'Ingrédients',
  nutrients: 'Nutriments pour 100 g',
  label: 'Étiquette',
  estimate: 'Estimation',
  coverage: 'Couverture',
  coverageNote: 'La part du produit dont les ingrédients donnent une valeur.',
  confidence: 'Confiance',
  agrees: 'Concorde',
  declaredBelow: 'Étiquette en dessous',
  declaredAbove: 'Étiquette au-dessus',
  constrained: 'Utilisé pour l’estimation',
  notEstimated: 'Non estimé',
  declaredBelowNote:
    'L’étiquette déclare moins que les ingrédients au minimum.',
  declaredAboveNote: 'L’étiquette déclare plus que les ingrédients au maximum.',
  constrainedNote: 'Concorde par construction.',
  groupAgree: '%(agree)s sur %(compared)s en accord avec l’étiquette',
  notCompared: 'Pas comparé à l’étiquette',
  legendTolerance: 'Tolérance de l’étiquette (Commission européenne)',
  tolerated: 'Dans la tolérance',
  toleratedNote: 'Diffère de plus que l’arrondi, mais dans la tolérance.',
  nutrientsMl: 'Nutriments pour 100 ml',
  per: 'Quantités pour',
  unitG: '100 g',
  unitMl: '100 ml',
  density: 'Densité utilisée : %(low)s à %(high)s g/ml',
};

const range = (low, point, high) => ({ low, point, high });
const declared = (amount, low = amount, high = amount, tolerance = {}) => ({
  amount,
  low,
  high,
  ...tolerance,
});
const confidence = (score) => ({
  score,
  coverage: '1',
  quality: '0.8',
  uncertainty: '0.2',
  agreement: null,
});

const nutrient = (overrides) => ({
  code: 'x',
  name: 'X',
  unit: 'g',
  group: 'macronutrient',
  group_label: 'Macronutriment',
  estimated: null,
  coverage: null,
  confidence: null,
  declared: null,
  verdict: null,
  constrained: false,
  tolerated: false,
  other_readings: [],
  ...overrides,
});

const data = {
  ingredients: [
    {
      name: 'Sucre',
      depth: 0,
      declared: '30',
      estimated: range('28', '30', '32'),
    },
    {
      name: 'Noisettes',
      depth: 0,
      declared: null,
      estimated: range('10', '13', '15'),
    },
    { name: 'Poudre de lait', depth: 1, declared: null, estimated: null },
  ],
  nutrients: [
    nutrient({
      code: 'carbohydrates',
      name: 'Glucides',
      estimated: range('55', '57', '60'),
      coverage: '100',
      confidence: confidence('0.62'),
      declared: declared('57.5', '57', '58'),
      verdict: 'agrees',
    }),
    nutrient({
      code: 'fat',
      name: 'Matières grasses',
      estimated: range('20', '25', '28'),
      coverage: '100',
      declared: declared('30.9'),
      verdict: 'declared_above',
    }),
    nutrient({
      code: 'proteins',
      name: 'Protéines',
      estimated: range('5', '6', '7'),
      coverage: '100',
      declared: declared('6'),
      verdict: 'agrees',
      constrained: true,
    }),
    nutrient({
      code: 'salt',
      name: 'Sel',
      declared: declared('0.107'),
      verdict: 'not_estimated',
    }),
    nutrient({
      code: 'vitamin_e',
      name: 'Vitamine E',
      unit: 'mg',
      group: 'vitamin',
      group_label: 'Vitamine',
      estimated: range('1.2', '2', null),
      coverage: '60',
    }),
    nutrient({
      code: 'iron',
      name: 'Fer',
      unit: 'mg',
      group: 'mineral',
      group_label: 'Minéral',
      estimated: range('3', '4', '5'),
      coverage: '100',
      declared: declared('1.5'),
      verdict: 'declared_below',
    }),
  ],
};

function mount({ tables = [], panel = data } = {}) {
  return render(
    <EstimatePanel
      data={panel}
      labels={labels}
      languageCode="fr-fr"
      tables={tables}
    />,
  );
}

const gauge = (name) =>
  screen.getByRole('img', { name: new RegExp(`^${name}`) });
const group = (name) => screen.getByRole('button', { name: new RegExp(name) });

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe('the estimate as gauges', () => {
  it('shows the ingredients, and the groups of nutrients closed, by default', () => {
    mount();

    expect(gauge('Sucre')).toBeInTheDocument();
    for (const name of ['Macronutriment', 'Vitamine', 'Minéral']) {
      expect(group(name)).toHaveAttribute('aria-expanded', 'false');
    }
    expect(screen.queryByRole('img', { name: /^Glucides/ })).toBeNull();
    expect(screen.getByRole('button', { name: 'Jauges' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('says of each group how many of its estimates the label agrees with', () => {
    mount();

    // Carbohydrates agree; the fat is over; the protein agrees by construction and
    // confirms nothing, and the salt was not estimated.
    expect(group('Macronutriment')).toHaveTextContent(
      '1 sur 2 en accord avec l’étiquette',
    );
    expect(group('Minéral')).toHaveTextContent(
      '0 sur 1 en accord avec l’étiquette',
    );
    // Nothing of the label to set the vitamin against.
    expect(group('Vitamine')).toHaveTextContent('Pas comparé à l’étiquette');
    // And the whole of them, above the groups.
    expect(
      screen.getByText('1 sur 3 en accord avec l’étiquette'),
    ).toBeInTheDocument();
  });

  it('opens a group to its gauges, and closes it again', () => {
    mount();

    fireEvent.click(group('Macronutriment'));

    expect(group('Macronutriment')).toHaveAttribute('aria-expanded', 'true');
    expect(gauge('Glucides')).toBeInTheDocument();
    expect(gauge('Sel')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: /^Fer/ })).toBeNull();

    fireEvent.click(group('Macronutriment'));

    expect(screen.queryByRole('img', { name: /^Glucides/ })).toBeNull();
  });

  it('says the estimate, its range, the label and the verdict in words', () => {
    mount();
    fireEvent.click(group('Macronutriment'));

    expect(gauge('Glucides').getAttribute('aria-label')).toMatch(
      /Estimation 57 g \(55 – 60\) ; Étiquette 57,5 g ; Concorde$/,
    );
    expect(gauge('Sel').getAttribute('aria-label')).toMatch(
      /Étiquette 0,107 g ; Non estimé$/,
    );
  });

  it('colours the range by what the label says of it', () => {
    mount();
    fireEvent.click(group('Macronutriment'));
    fireEvent.click(group('Minéral'));
    fireEvent.click(group('Vitamine'));

    const band = (name) => gauge(name).querySelector('.est-band');
    expect(band('Glucides')).toHaveClass('est-band--agrees');
    expect(band('Matières grasses')).toHaveClass('est-band--differs');
    expect(band('Fer')).toHaveClass('est-band--differs');
    expect(band('Protéines')).toHaveClass('est-band--used');
    // Nothing of the label to set it against.
    expect(band('Vitamine E')).toHaveClass('est-band--none');
  });

  it('names the verdict under the nutrient, with what it means', () => {
    mount();
    fireEvent.click(group('Macronutriment'));

    const row = (name) => gauge(name).closest('.est-row');
    expect(within(row('Glucides')).getByText('Concorde')).toBeInTheDocument();
    const over = within(row('Matières grasses')).getByText(
      'Étiquette au-dessus',
    );
    expect(over).toHaveAttribute('title', labels.declaredAboveNote);
    expect(
      within(row('Protéines')).getByText('Utilisé pour l’estimation'),
    ).toHaveAttribute('title', labels.constrainedNote);
    expect(within(row('Sel')).getByText('Non estimé')).toBeInTheDocument();
  });

  it('draws the label as a tick, and the rounding it stands for where it can be seen', () => {
    mount();
    fireEvent.click(group('Macronutriment'));

    // 57 to 58 of 69: a rounding that is wide enough; 30.9 to 30.9 is not.
    expect(gauge('Glucides').querySelector('.est-label-tick')).not.toBeNull();
    expect(gauge('Glucides').querySelector('.est-rounding')).not.toBeNull();
    expect(gauge('Matières grasses').querySelector('.est-rounding')).toBeNull();
  });

  it('draws a nutrient the label declares and no ingredient gives as its tick alone', () => {
    mount();
    fireEvent.click(group('Macronutriment'));

    const salt = gauge('Sel');
    expect(salt.querySelector('.est-band')).toBeNull();
    expect(salt.querySelector('.est-point')).toBeNull();
    expect(salt.querySelector('.est-label-tick')).not.toBeNull();
    expect(within(salt.closest('.est-row')).getByText('–')).toBeInTheDocument();
  });

  it('opens the range that has no upper end, and says what is not covered', () => {
    mount();
    fireEvent.click(group('Vitamine'));

    const vitamin = gauge('Vitamine E');
    expect(vitamin.querySelector('.est-band')).toHaveClass('est-band--open');
    expect(vitamin.getAttribute('aria-label')).toMatch(/\(≥ 1,2\)/);
    expect(
      within(vitamin.closest('.est-row')).getByText('Couverture 60 %'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Pointillé : aucun maximum n’est connu.'),
    ).toBeInTheDocument();
  });

  it('gives the confidence as a meter between 0 and 1', () => {
    mount();
    fireEvent.click(group('Macronutriment'));

    const meter = within(gauge('Glucides').closest('.est-row')).getByRole(
      'meter',
      {
        name: 'Confiance',
      },
    );
    expect(meter).toHaveAttribute('aria-valuenow', '0.62');
    expect(meter.firstChild).toHaveStyle({ width: '62%' });
    expect(
      within(meter.closest('.est-row')).getByText('Confiance 0,62'),
    ).toBeInTheDocument();
    expect(
      within(gauge('Matières grasses').closest('.est-row')).queryByRole(
        'meter',
      ),
    ).toBeNull();
  });

  it('puts the shares of the ingredients on one track, and indents the parts', () => {
    mount();

    // The track is 32 x 1.15 = 36.8 long for all of them.
    const sugar = gauge('Sucre').querySelector('.est-band');
    const hazelnuts = gauge('Noisettes').querySelector('.est-band');
    expect(parseFloat(sugar.style.left)).toBeCloseTo((28 / 36.8) * 100);
    expect(parseFloat(hazelnuts.style.left)).toBeCloseTo((10 / 36.8) * 100);
    const milk = gauge('Poudre de lait').closest('.est-row');
    expect(
      milk.querySelector('.est-name').style.getPropertyValue('--est-depth'),
    ).toBe('1');
    expect(gauge('Poudre de lait').querySelector('.est-band')).toBeNull();
  });
});

describe('the choice between the gauges and the tables', () => {
  const tables = () => {
    const found = [
      document.createElement('div'),
      document.createElement('div'),
    ];
    document.body.append(...found);
    return found;
  };

  it('hides the tables of the page while the gauges are shown, and shows them back', () => {
    const [ingredients, nutrients] = tables();
    mount({ tables: [ingredients, nutrients] });
    expect(ingredients.hidden && nutrients.hidden).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: 'Tableau' }));

    expect(ingredients.hidden || nutrients.hidden).toBe(false);
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.getByRole('button', { name: 'Tableau' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );

    fireEvent.click(screen.getByRole('button', { name: 'Jauges' }));

    expect(ingredients.hidden && nutrients.hidden).toBe(true);
    expect(gauge('Sucre')).toBeInTheDocument();
  });

  it('leaves the tables as they were when it goes', () => {
    const [table] = tables();
    const { unmount } = mount({ tables: [table] });
    expect(table.hidden).toBe(true);

    unmount();

    expect(table.hidden).toBe(false);
  });

  it('keeps the choice and the groups that are open for the next visit', () => {
    const first = mount();
    fireEvent.click(group('Minéral'));
    expect(window.localStorage.getItem('products.estimateOpenGroups')).toBe(
      '["mineral"]',
    );
    first.unmount();

    mount();

    expect(group('Minéral')).toHaveAttribute('aria-expanded', 'true');
    expect(gauge('Fer')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Tableau' }));
    expect(window.localStorage.getItem('products.estimateMode')).toBe('table');
  });

  it('unfolds and folds all the groups, in the gauges only', () => {
    mount();

    fireEvent.click(screen.getByRole('button', { name: 'Tout déplier' }));

    expect(gauge('Glucides')).toBeInTheDocument();
    expect(gauge('Fer')).toBeInTheDocument();
    expect(gauge('Vitamine E')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Tout replier' }));

    expect(screen.queryByRole('img', { name: /^Glucides/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Tableau' }));
    expect(screen.queryByRole('button', { name: /Tout/ })).toBeNull();
  });

  it('works without storage', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    mount();

    fireEvent.click(group('Minéral'));

    expect(gauge('Fer')).toBeInTheDocument();
  });
});

describe('the tolerance of the label', () => {
  const tolerance = { tolerance_low: '9.9', tolerance_high: '16.1' };
  const withTolerance = {
    ...data,
    nutrients: [
      nutrient({
        code: 'saturated_fat',
        name: 'Saturés',
        estimated: range('13.7', '13.8', '13.9'),
        coverage: '100',
        declared: declared('13', '12.5', '13.5', tolerance),
        verdict: 'agrees',
        constrained: true,
        tolerated: true,
      }),
      nutrient({
        code: 'fat',
        name: 'Matières grasses',
        estimated: range('20', '25', '28'),
        coverage: '100',
        declared: declared('30.9', '30.85', '30.95', {
          tolerance_low: '24.7',
          tolerance_high: '37.1',
        }),
        verdict: 'declared_above',
      }),
      nutrient({
        code: 'carbohydrates',
        name: 'Glucides',
        estimated: range('55', '57', '60'),
        coverage: '100',
        declared: declared('57.5', '57', '58', {
          tolerance_low: '46',
          tolerance_high: '69',
        }),
        verdict: 'agrees',
      }),
    ],
  };

  it('draws a band where the label agrees only within it, or differs despite it', () => {
    mount({ panel: withTolerance });
    fireEvent.click(group('Macronutriment'));

    expect(gauge('Saturés').querySelector('.est-tolerance')).not.toBeNull();
    expect(
      gauge('Matières grasses').querySelector('.est-tolerance'),
    ).not.toBeNull();
    // Agreeing on the rounding alone, it has nothing to add.
    expect(gauge('Glucides').querySelector('.est-tolerance')).toBeNull();
  });

  it('says in a badge that the label was read with it', () => {
    mount({ panel: withTolerance });
    fireEvent.click(group('Macronutriment'));

    const row = gauge('Saturés').closest('.est-row');
    expect(within(row).getByText('Dans la tolérance')).toHaveAttribute(
      'title',
      labels.toleratedNote,
    );
    expect(gauge('Saturés').getAttribute('aria-label')).toMatch(
      /Dans la tolérance$/,
    );
    const plain = gauge('Glucides').closest('.est-row');
    expect(within(plain).queryByText('Dans la tolérance')).toBeNull();
  });

  it('explains the band in the legend only when one is drawn', () => {
    const { unmount } = mount({ panel: withTolerance });
    expect(
      screen.getByText('Tolérance de l’étiquette (Commission européenne)'),
    ).toBeInTheDocument();
    unmount();

    mount();

    expect(
      screen.queryByText('Tolérance de l’étiquette (Commission européenne)'),
    ).toBeNull();
  });
});

describe('the choice of the unit, per 100 g or per 100 ml', () => {
  // An oil: a millilitre weighs 0.9 to 0.92 g. Estimated per 100 g, the label as it is
  // printed per 100 ml: 91 g of fat (90.5 to 91.5).
  const density = { low: '0.9', point: '0.91', high: '0.92' };
  const oil = (labelUnit, printed) => ({
    label_unit: labelUnit,
    density,
    ingredients: [],
    nutrients: [
      nutrient({
        code: 'fat',
        name: 'Matières grasses',
        estimated: range('100', '100', '100'),
        coverage: '100',
        declared: printed,
        verdict: 'agrees',
      }),
    ],
  });
  const perMillilitre = oil('ml', declared('91', '90.5', '91.5'));
  const summary = () => gauge('Matières grasses').getAttribute('aria-label');
  const unitButton = (name) => screen.getByRole('button', { name });

  it('shows the amounts in the unit of the label at first, with the density used', () => {
    mount({ panel: perMillilitre });
    fireEvent.click(group('Macronutriment'));

    expect(screen.getByText('Nutriments pour 100 ml')).toBeInTheDocument();
    expect(unitButton('100 ml')).toHaveAttribute('aria-pressed', 'true');
    expect(summary()).toMatch(
      /Estimation 91 g \(90 – 92\) ; Étiquette 91 g ; Concorde$/,
    );
    expect(
      screen.getByText('Densité utilisée : 0,9 à 0,92 g/ml'),
    ).toBeInTheDocument();
  });

  it('converts the estimate and the label to the other unit', () => {
    mount({ panel: perMillilitre });
    fireEvent.click(group('Macronutriment'));

    fireEvent.click(unitButton('100 g'));

    expect(screen.getByText('Nutriments pour 100 g')).toBeInTheDocument();
    expect(unitButton('100 g')).toHaveAttribute('aria-pressed', 'true');
    // 91 g per 100 ml of 0.91 g/ml is 100 g per 100 g.
    expect(summary()).toMatch(
      /Estimation 100 g \(100 – 100\) ; Étiquette 100 g/,
    );
  });

  it('shows a label given per 100 g in millilitres on demand', () => {
    mount({ panel: oil('g', declared('100', '99.5', '100.5')) });
    fireEvent.click(group('Macronutriment'));
    expect(screen.getByText('Nutriments pour 100 g')).toBeInTheDocument();

    fireEvent.click(unitButton('100 ml'));

    expect(summary()).toMatch(/Estimation 91 g \(90 – 92\) ; Étiquette 91 g/);
  });

  it('keeps the choice for the next visit', () => {
    const first = mount({ panel: perMillilitre });
    fireEvent.click(unitButton('100 g'));
    expect(window.localStorage.getItem('products.estimateUnit')).toBe('g');
    first.unmount();

    mount({ panel: perMillilitre });

    expect(screen.getByText('Nutriments pour 100 g')).toBeInTheDocument();
  });

  it('has no choice where the density is not known, and shows what it has', () => {
    mount({ panel: { ...perMillilitre, density: null } });
    fireEvent.click(group('Macronutriment'));

    expect(screen.queryByRole('group', { name: 'Quantités pour' })).toBeNull();
    expect(screen.queryByText(/Densité utilisée/)).toBeNull();
    expect(screen.getByText('Nutriments pour 100 g')).toBeInTheDocument();
    // Neither converted: the estimate per 100 g, and the label as printed.
    expect(summary()).toMatch(
      /Estimation 100 g \(100 – 100\) ; Étiquette 91 g/,
    );
  });

  it('is offered in the gauges only', () => {
    mount({ panel: perMillilitre });
    expect(
      screen.getByRole('group', { name: 'Quantités pour' }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Tableau' }));

    expect(screen.queryByRole('group', { name: 'Quantités pour' })).toBeNull();
  });

  it('works without storage', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    mount({ panel: perMillilitre });

    fireEvent.click(unitButton('100 g'));

    expect(screen.getByText('Nutriments pour 100 g')).toBeInTheDocument();
  });
});
