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
  legendLabel: 'Chiffre de l’étiquette',
  legendEstimate: 'Fourchette estimée',
  ingredient: 'Ingrédient',
  nutrient: 'Nutriment',
  columnEstimate: 'Meilleure estimation',
  ingredients: 'Ingrédients',
  added: 'quantité ajoutée',
  nutrients: 'Nutriments pour 100 g',
  nutrientsMl: 'Nutriments pour 100 ml',
  per: 'Quantités pour',
  unitG: '100 g',
  unitMl: '100 ml',
  density: 'Densité utilisée : %(low)s à %(high)s g/ml',
  label: 'Étiquette',
  estimate: 'Estimation',
  labelAt: 'étiquette %(value)s',
  rangeOpen: 'au moins %(low)s · pas de borne haute',
  agrees: 'L’étiquette concorde',
  declaredBelow: 'Étiquette plus basse que le minimum possible',
  declaredAbove: 'Étiquette plus haute que le maximum possible',
  constrained: 'Point de départ du calcul',
  tolerated: 'Hors fourchette, dans la tolérance de la Commission',
  notEstimated: 'Non estimé : aucun ingrédient n’en donne',
  estimateOnly: 'Estimation seule, sans étiquette',
  toleratedNote: 'Diffère de plus que l’arrondi, mais dans la tolérance.',
  declaredBelowNote:
    'L’étiquette déclare moins que les ingrédients au minimum.',
  declaredAboveNote: 'L’étiquette déclare plus que les ingrédients au maximum.',
  constrainedNote: 'Concorde par construction.',
  summaryChecked:
    'Vérifiés par les ingrédients : %(checked)s sur %(total)s chiffres de l’étiquette.',
  summaryStart:
    'Ceux qui ont servi à calculer les parts concordent forcément et ne prouvent rien.',
  chipChecked: 'Vérifiés : %(n)s',
  chipStart: 'Points de départ : %(n)s',
  chipGap: 'Écarts : %(n)s',
  notCompared: 'Pas comparé à l’étiquette',
  reliability: 'Fiabilité',
  reliabilityLow: 'Fiabilité faible',
  reliabilityMedium: 'Fiabilité moyenne',
  reliabilityGood: 'Fiabilité bonne',
  reliabilityIntro: 'Le produit de quatre facteurs :',
  coverage: 'Couverture',
  coverageNote: 'La part du produit dont les ingrédients donnent une valeur.',
  factorQuality: 'Qualité des données',
  qualityNote: 'La note des aliments (CIQUAL).',
  factorRecipe: 'Recette bien connue',
  recipeNote: '1 moins l’incertitude.',
  factorAgreement: 'Accord des vérifications',
  agreementNote: 'Un tiret quand aucune ne pouvait échouer.',
  limiting: 'ce qui la limite',
  detailShow: 'Voir le détail de %(name)s',
  detailHide: 'Masquer le détail de %(name)s',
  detailRounding: 'Écrit avec son arrondi : il vaut de %(low)s à %(high)s.',
  detailTolerance: 'Tolérance de la Commission : de %(low)s à %(high)s.',
  detailNoTolerance: 'Aucune tolérance ne s’applique à ce chiffre.',
  bestGuess: 'au mieux %(point)s',
  rangeNote: 'L’estimation est une fourchette, pas un chiffre.',
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

  it('says once what the ingredients check of the label, and what they do not', () => {
    mount();

    // Carbohydrates agree; the fat and the iron differ; the protein was a starting
    // point and confirms nothing; the salt and the vitamin have nothing to be set
    // against: four figures of the label are compared.
    const summary = document.querySelector('.est-summary');
    expect(summary).toHaveTextContent(
      'Vérifiés par les ingrédients : 1 sur 4 chiffres de l’étiquette.',
    );
    expect(summary).toHaveTextContent('ne prouvent rien');
    expect(summary).toHaveTextContent('Vérifiés : 1');
    expect(summary).toHaveTextContent('Points de départ : 1');
    expect(summary).toHaveTextContent('Écarts : 2');
  });

  it('does not say they prove nothing where no figure was a starting point', () => {
    const { nutrients } = data;
    mount({
      panel: {
        ...data,
        nutrients: nutrients.filter((found) => found.code === 'carbohydrates'),
      },
    });

    const summary = document.querySelector('.est-summary');
    expect(summary).toHaveTextContent('1 sur 1 chiffres');
    expect(summary).not.toHaveTextContent('ne prouvent rien');
  });

  it('says so where no figure of the label is compared', () => {
    mount({
      panel: {
        ...data,
        nutrients: data.nutrients.filter((found) => found.code === 'vitamin_e'),
      },
    });

    expect(document.querySelector('.est-summary')).toBeNull();
    expect(screen.getAllByText('Pas comparé à l’étiquette')).toHaveLength(2);
  });

  it('says of each group what the label makes of its estimates', () => {
    mount();

    expect(group('Macronutriment')).toHaveTextContent(
      'Vérifiés : 1 · Points de départ : 1 · Écarts : 1',
    );
    expect(group('Minéral')).toHaveTextContent('Écarts : 1');
    // Nothing of the label to set the vitamin against.
    expect(group('Vitamine')).toHaveTextContent('Pas comparé à l’étiquette');
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

  it('says what the marks are once, above the rows', () => {
    mount();

    expect(screen.getAllByText('Chiffre de l’étiquette')).toHaveLength(2);
    expect(screen.getAllByText('Fourchette estimée')).toHaveLength(2);
    expect(screen.getByText('Nutriment')).toBeInTheDocument();
  });

  it('says the estimate, its range, the label and the verdict in words', () => {
    mount();
    fireEvent.click(group('Macronutriment'));

    expect(gauge('Glucides').getAttribute('aria-label')).toMatch(
      /Estimation 57 g \(55 – 60\) ; Étiquette 57,5 g ; L’étiquette concorde$/,
    );
    expect(gauge('Sel').getAttribute('aria-label')).toMatch(
      /Étiquette 0,107 g ; Non estimé : aucun ingrédient n’en donne$/,
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

  it('says in a phrase under the nutrient what the label makes of it', () => {
    mount();
    fireEvent.click(group('Macronutriment'));
    fireEvent.click(group('Vitamine'));

    const verdict = (name) =>
      gauge(name).closest('.est-row').querySelector('.est-verdict');
    expect(verdict('Glucides')).toHaveTextContent('L’étiquette concorde');
    expect(verdict('Glucides')).toHaveClass('est-verdict--agrees');
    expect(verdict('Matières grasses')).toHaveTextContent(
      'Étiquette plus haute que le maximum possible',
    );
    expect(verdict('Matières grasses')).toHaveClass('est-verdict--differs');
    // A starting point is no verdict of agreement, though it agrees.
    expect(verdict('Protéines')).toHaveTextContent('Point de départ du calcul');
    expect(verdict('Protéines')).toHaveClass('est-verdict--used');
    expect(verdict('Sel')).toHaveTextContent('Non estimé : aucun ingrédient');
    expect(verdict('Vitamine E')).toHaveTextContent(
      'Estimation seule, sans étiquette',
    );
  });

  it('writes the figures where they are drawn: the label above, the range under', () => {
    mount();
    fireEvent.click(group('Macronutriment'));
    fireEvent.click(group('Vitamine'));

    const glucides = gauge('Glucides');
    expect(glucides.querySelector('.est-text--label')).toHaveTextContent(
      'étiquette 57,5',
    );
    expect(glucides.querySelector('.est-text--range')).toHaveTextContent(
      '55 – 60',
    );
    expect(glucides.querySelector('.est-diamond')).not.toBeNull();
    // An open range says there is no upper end, and the ingredients' coverage is why.
    expect(
      gauge('Vitamine E').querySelector('.est-text--range'),
    ).toHaveTextContent('au moins 1,2 · pas de borne haute');
    expect(gauge('Vitamine E').querySelector('.est-band')).toHaveClass(
      'est-band--open',
    );
  });

  it('gives the best estimate as the value of the row', () => {
    mount();
    fireEvent.click(group('Macronutriment'));

    expect(
      within(gauge('Glucides').closest('.est-row')).getByText('≈ 57 g'),
    ).toBeInTheDocument();
  });

  it('draws a nutrient the label declares and no ingredient gives as its diamond alone', () => {
    mount();
    fireEvent.click(group('Macronutriment'));

    const salt = gauge('Sel');
    expect(salt.querySelector('.est-band')).toBeNull();
    expect(salt.querySelector('.est-text--range')).toBeNull();
    expect(salt.querySelector('.est-diamond')).not.toBeNull();
    expect(within(salt.closest('.est-row')).getByText('–')).toBeInTheDocument();
  });

  it('gives how far to trust an estimate in three dots and in words', () => {
    mount();
    fireEvent.click(group('Macronutriment'));

    const row = gauge('Glucides').closest('.est-row');
    expect(within(row).getByText('Fiabilité bonne')).toBeInTheDocument();
    expect(row.querySelectorAll('.est-dot--on')).toHaveLength(3);
    // Where there is no confidence there is no word, and no dots.
    const fat = gauge('Matières grasses').closest('.est-row');
    expect(fat.querySelector('.est-dot')).toBeNull();
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

  it('says nothing of the label to the ingredients, which have no verdict, nor detail', () => {
    mount();

    const sugar = gauge('Sucre').closest('.est-row');
    expect(sugar.querySelector('.est-verdict')).toBeNull();
    expect(sugar.querySelector('.est-toggle')).toBeNull();
    expect(sugar.querySelector('.est-text--label')).toHaveTextContent(
      'étiquette 30 %',
    );
  });
});

describe('the ingredients', () => {
  it('are rows as high as two lines: the label under the name, the range under the estimate', () => {
    mount();

    const sugar = gauge('Sucre').closest('.est-row');
    expect(sugar).toHaveClass('est-row--compact');
    expect(sugar.querySelector('.est-name .est-text--label')).toHaveTextContent(
      'étiquette 30 %',
    );
    expect(
      sugar.querySelector('.est-value .est-text--range'),
    ).toHaveTextContent('28 – 32 %');
    // The drawing is the track, the band and the diamond: no figure on it.
    expect(sugar.querySelector('.est-gauge .est-text--label')).toBeNull();
    expect(sugar.querySelector('.est-gauge .est-text--range')).toBeNull();
    expect(sugar.querySelector('.est-diamond')).not.toBeNull();
    // The figure of the nutrients is on the drawing, as it was.
    fireEvent.click(group('Macronutriment'));
    expect(gauge('Glucides').closest('.est-row')).not.toHaveClass(
      'est-row--compact',
    );
  });

  it('have no figure of the label under the name where there is none', () => {
    mount();

    const hazelnuts = gauge('Noisettes').closest('.est-row');
    expect(hazelnuts.querySelector('.est-name .est-text--label')).toBeNull();
    expect(hazelnuts.querySelector('.est-diamond')).toBeNull();
  });

  it('fold away under their head, which counts them, and stay so', () => {
    const first = mount();
    const head = screen.getByRole('button', { name: /Ingrédients/ });
    expect(head).toHaveAttribute('aria-expanded', 'true');
    expect(head).toHaveTextContent(String(data.ingredients.length));

    fireEvent.click(head);

    expect(head).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('img', { name: /^Sucre/ })).toBeNull();
    // The nutrients are not the ingredients': they are still there to open.
    expect(group('Macronutriment')).toBeInTheDocument();

    first.unmount();
    mount();
    expect(screen.getByRole('button', { name: /Ingrédients/ })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    expect(screen.queryByRole('img', { name: /^Sucre/ })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /Ingrédients/ }));
    expect(gauge('Sucre')).toBeInTheDocument();
  });
});

describe('a row opened', () => {
  const toggle = (name) =>
    screen.getByRole('button', { name: `Voir le détail de ${name}` });

  it('opens and closes with its button', () => {
    mount();
    fireEvent.click(group('Macronutriment'));

    expect(toggle('Glucides')).toHaveAttribute('aria-expanded', 'false');
    expect(document.querySelector('.est-detail')).toBeNull();

    fireEvent.click(toggle('Glucides'));

    const hide = screen.getByRole('button', {
      name: 'Masquer le détail de Glucides',
    });
    expect(hide).toHaveAttribute('aria-expanded', 'true');
    expect(document.querySelector('.est-detail')).not.toBeNull();

    fireEvent.click(hide);

    expect(document.querySelector('.est-detail')).toBeNull();
  });

  it('says what the label is, with its rounding, and what the estimate is', () => {
    mount();
    fireEvent.click(group('Macronutriment'));

    fireEvent.click(toggle('Glucides'));

    const detail = document.querySelector('.est-detail');
    expect(detail).toHaveTextContent('57,5 g');
    expect(detail).toHaveTextContent(
      'Écrit avec son arrondi : il vaut de 57 g à 58 g.',
    );
    expect(detail).toHaveTextContent('Aucune tolérance ne s’applique');
    expect(detail).toHaveTextContent('55 – 60 g');
    expect(detail).toHaveTextContent('au mieux 57 g');
    expect(detail).toHaveTextContent('L’estimation est une fourchette');
  });

  it('says what the verdict means in place of the general note', () => {
    mount();
    fireEvent.click(group('Macronutriment'));

    fireEvent.click(toggle('Matières grasses'));
    expect(document.querySelector('.est-detail')).toHaveTextContent(
      labels.declaredAboveNote,
    );
    // A figure that is written exactly has no rounding to say.
    expect(document.querySelector('.est-detail')).not.toHaveTextContent(
      'arrondi',
    );
    fireEvent.click(
      screen.getByRole('button', {
        name: 'Masquer le détail de Matières grasses',
      }),
    );

    fireEvent.click(toggle('Protéines'));
    expect(document.querySelector('.est-detail')).toHaveTextContent(
      labels.constrainedNote,
    );
  });

  it('gives the parts of the confidence, and the one that holds it down', () => {
    mount();
    fireEvent.click(group('Macronutriment'));

    fireEvent.click(toggle('Glucides'));

    const detail = document.querySelector('.est-detail');
    expect(detail).toHaveTextContent('Fiabilité 0,62');
    const parts = [...detail.querySelectorAll('.est-factors li')];
    expect(
      parts.map((part) => part.querySelector('.est-factor-head').textContent),
    ).toEqual([
      'Couverture1,00',
      'Qualité des données · ce qui la limite0,80',
      'Recette bien connue0,80',
      'Accord des vérifications–',
    ]);
    expect(parts[1]).toHaveClass('est-factor--limiting');
    expect(
      parts.filter((part) => part.matches('.est-factor--limiting')),
    ).toHaveLength(1);
    expect(parts[1].querySelector('.est-factor-bar > span')).toHaveStyle({
      width: '80%',
    });
  });

  it('has no confidence to give where the estimate has none', () => {
    mount();
    fireEvent.click(group('Macronutriment'));

    fireEvent.click(toggle('Matières grasses'));

    expect(document.querySelector('.est-detail')).not.toHaveTextContent(
      'Fiabilité',
    );
  });

  it('has no detail for a figure there is nothing to say of', () => {
    mount({
      panel: {
        ...data,
        nutrients: [nutrient({ code: 'y', name: 'Rien' })],
      },
    });
    fireEvent.click(group('Macronutriment'));

    expect(screen.queryByRole('button', { name: /Voir le détail/ })).toBeNull();
  });
});

describe('the tolerance of the label', () => {
  const tolerance = { tolerance_low: '9.9', tolerance_high: '16.1' };
  const withTolerance = {
    ...data,
    nutrients: [
      nutrient({
        code: 'salt',
        name: 'Sel',
        estimated: range('1.1', '1.3', '1.5'),
        coverage: '100',
        confidence: confidence('0.5'),
        declared: declared('1.7', '1.65', '1.75', tolerance),
        verdict: 'agrees',
        tolerated: true,
      }),
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
    ],
  };

  it('says the label agrees within it, in the phrase of the verdict', () => {
    mount({ panel: withTolerance });
    fireEvent.click(group('Macronutriment'));

    const row = gauge('Sel').closest('.est-row');
    expect(within(row).getByText(labels.tolerated)).toBeInTheDocument();
    expect(row.querySelector('.est-verdict')).toHaveClass(
      'est-verdict--agrees',
    );
    expect(gauge('Sel').getAttribute('aria-label')).toMatch(
      /Hors fourchette, dans la tolérance de la Commission$/,
    );
    // The range is not drawn wider for it.
    expect(gauge('Sel').querySelector('.est-tolerance')).toBeNull();
  });

  it('gives it in the detail, as the range the label stands for with it', () => {
    mount({ panel: withTolerance });
    fireEvent.click(group('Macronutriment'));

    fireEvent.click(
      screen.getByRole('button', { name: 'Voir le détail de Sel' }),
    );

    expect(document.querySelector('.est-detail')).toHaveTextContent(
      'Tolérance de la Commission : de 9,9 g à 16,1 g.',
    );
    expect(document.querySelector('.est-detail')).toHaveTextContent(
      labels.toleratedNote,
    );
  });

  it('leaves a figure the estimate was worked out with a starting point, whatever the tolerance', () => {
    mount({ panel: withTolerance });
    fireEvent.click(group('Macronutriment'));

    const row = gauge('Saturés').closest('.est-row');
    expect(row.querySelector('.est-verdict')).toHaveTextContent(
      'Point de départ du calcul',
    );
  });
});

describe('what an ingredient that is a nutrient adds', () => {
  const withVitamin = (added = range('0', '20', '25.5')) => ({
    ...data,
    ingredients: [
      ...data.ingredients,
      {
        name: 'Vitamine C',
        depth: 0,
        declared: null,
        estimated: range('0', '0.02', '0.1'),
        added,
        added_unit: 'mg',
      },
    ],
  });

  it('is an amount on a track of its own, and not a share among the others', () => {
    mount({ panel: withVitamin() });

    const row = gauge('Vitamine C \\(quantité ajoutée\\)').closest('.est-row');
    expect(within(row).getByText('≈ 20 mg')).toBeInTheDocument();
    expect(within(row).queryByText('≈ 0,02 %')).toBeNull();
    // The shares keep the track they had: 32 x 1.15 = 36.8 long for all of them.
    const sugar = gauge('Sucre').querySelector('.est-band');
    expect(parseFloat(sugar.style.left)).toBeCloseTo((28 / 36.8) * 100);
  });

  it('is left alone for an ingredient that adds nothing the label says', () => {
    mount({ panel: withVitamin(null) });

    expect(gauge('Vitamine C').closest('.est-row')).toHaveTextContent('0,02 %');
    expect(screen.queryByText(/quantité ajoutée/)).toBeNull();
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
      /Estimation 91 g \(90 – 92\) ; Étiquette 91 g ; L’étiquette concorde$/,
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
