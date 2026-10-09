import { render } from '@testing-library/react';
import { vi } from 'vitest';

import { MealsApp } from './MealsApp.jsx';

// Stands in for the |json_script blob rendered by MealsView: the real French
// catalogue entries, so a regression back to hardcoded English fails these.
export const labels = {
  loading: 'Chargement…',
  loadError: 'Les repas n’ont pas pu être chargés.',
  saveError: 'Le changement n’a pas pu être enregistré.',
  previousDay: 'Jour précédent',
  nextDay: 'Jour suivant',
  day: 'Jour',
  today: 'Aujourd’hui',
  emptyInventory: 'Votre inventaire est vide.',
  goInventory: 'Aller à l’inventaire',
  serving: 'portion',
  quantity: 'Quantité',
  unit: 'Unité',
  noMass: 'pas de portion',
  remove: 'Retirer du repas',
  addProduct: 'Ajouter un produit',
  chooseProduct: 'Choisir un produit…',
  add: 'Ajouter',
  emptyMeal: 'Rien dans ce repas.',
  noProfile: 'Renseignez votre profil.',
  myNeeds: 'Mes besoins',
  emptyDay: 'Mettez des produits dans un repas.',
  dayTitle: 'La journée face à vos besoins',
  coverageNote:
    'Couverture : la part des aliments dont la composition donne une valeur.',
  nutrient: 'Nutriment',
  total: 'Total',
  need: 'Besoin',
  status: 'Statut',
  coverage: 'Couverture',
  ratios: 'Rapports',
  ratio: 'Rapport',
  inMoles: 'en moles',
  below: 'Sous',
  within: 'Atteint',
  above: 'Au-dessus',
  unknown: 'Inconnu',
  uncertain: 'Pas certain',
  proposeDay: 'Proposer un jour',
  proposing: 'Recherche du meilleur jour…',
  proposeError: 'Aucun jour n’a pu être proposé.',
  proposeNeedsProfile: 'Renseignez votre profil.',
  proposalTitle: 'Jour proposé',
  closeProposal: 'Fermer',
  proposal_optimal: 'Le meilleur jour que permet l’inventaire.',
  proposal_time_limit: 'Le temps est écoulé : voici le meilleur jour trouvé.',
  proposal_failed: 'Aucun jour n’a pu être calculé.',
  proposal_no_candidates: 'Aucun produit de l’inventaire n’a de composition.',
  skipped: 'Laissés de côté, sans valeur d’énergie :',
  useDay: 'Utiliser ce jour',
  confirmReplace: 'Remplacer ce qui est dans ce jour ?',
  limitsTitle: 'Limites pour le jour proposé',
  limitsHelp: 'Choisissez dans quels repas un produit peut être.',
  limitsMeals: 'Repas',
  limitsMost: 'Au plus par jour',
  product: 'Produit',
  save: 'Enregistrer',
  saved: 'Enregistré',
  suggestFoods: 'Suggérer des aliments',
  suggesting: 'Recherche d’aliments…',
  suggestError: 'Aucun aliment n’a pu être suggéré.',
  suggestionsTitle: 'Aliments à se procurer',
  suggestion_optimal:
    'Avec ces aliments, %(after)s besoins sur %(total)s ne sont pas couverts, contre %(before)s sans.',
  suggestion_time_limit:
    'Le temps est écoulé : %(after)s sur %(total)s, contre %(before)s sans.',
  suggestion_failed: 'Aucun jour n’a pu être calculé.',
  suggestion_no_gaps: 'Votre inventaire ne manque de rien.',
  suggestion_no_foods: 'Aucun aliment de la table ne comble ce qui manque.',
  suggestion_no_suggestion: 'Aucun aliment ne vaut la peine de ce qui manque.',
  suggestionCaution:
    'Une suggestion ne compte que la composition : contrôlez-la avant d’agir.',
  suggestedDay: 'Voir la journée avec ces aliments',
  suggestedFood: 'suggéré',
  coversNeed: 'couvre le besoin',
  ofNeed: '%(percent)s du besoin',
  view: 'Affichage',
  viewGauges: 'Jauges',
  viewTable: 'Tableau',
  legendZone: 'Attendu',
  legendRange: 'Fourchette de la valeur',
  legendUncertain: 'Pas certain',
  legendOpen: 'Pointillé : aucun maximum n’est connu.',
  shareOfMinimum: 'Part du minimum',
  shareOfLimit: 'Part de la limite',
  totalQuantity: 'Quantité totale',
  packageShare: '%(percent)s d’un paquet de %(package)s',
};

export const BREAD = {
  barcode: '3228857002245',
  name: 'Pain de mie',
  serving: { quantity: '35.70', unit: 'g', name: '1 tranche' },
  package: { quantity: '500.00', unit: 'g' },
  added_at: '2026-10-09T10:00:00Z',
};
export const MUESLI = {
  barcode: '3229820794556',
  name: 'Muesli',
  serving: null,
  package: { quantity: '375.00', unit: 'g' },
  added_at: '2026-10-09T10:00:00Z',
};

export const total = (
  amount,
  low = amount,
  high = amount,
  coverage = '100',
) => ({
  amount,
  low,
  high,
  coverage,
});

export function meal(kind, label, items = [], totals = {}) {
  return { kind, label, items, mass: '0', totals };
}

export function day(overrides = {}) {
  return {
    day: '2026-10-09',
    meals: [
      meal('breakfast', 'Petit-déjeuner'),
      meal('lunch', 'Déjeuner'),
      meal('snack', 'Collation'),
      meal('dinner', 'Dîner'),
    ],
    mass: '0',
    totals: {},
    nutrients: {},
    needs: null,
    ratios: null,
    ...overrides,
  };
}

export const breadItem = {
  id: 7,
  barcode: BREAD.barcode,
  name: BREAD.name,
  quantity: '2.00',
  unit: 'serving',
  grams: '71.40',
  serving: BREAD.serving,
  package: BREAD.package,
};

export const withBread = (extra = {}) =>
  day({
    mass: '71.4',
    meals: [
      meal('breakfast', 'Petit-déjeuner', [breadItem], {
        energy: total('3766.68', '3700', '3800'),
        proteins: total('7.854', '7.5', '8.2'),
      }),
      meal('lunch', 'Déjeuner'),
      meal('snack', 'Collation'),
      meal('dinner', 'Dîner'),
    ],
    totals: { energy: total('3766.68', '3700', '3800') },
    nutrients: {
      energy: { name: 'Énergie', unit: 'kJ' },
      proteins: { name: 'Protéines', unit: 'g' },
    },
    ...extra,
  });

export const ok = (body) => ({ ok: true, json: async () => body });

/** fetch, answering by method and URL; records what was asked. */
export function stubFetch(routes) {
  // Nothing is limited unless a test says so.
  const known = { 'GET /api/v1/meals/limits/': ok([]), ...routes };
  const fetch = vi.fn(async (url, options = {}) => {
    const key = `${options.method ?? 'GET'} ${url}`;
    const answer = known[key];
    if (!answer) throw new Error(`unexpected request: ${key}`);
    return typeof answer === 'function' ? answer(options) : answer;
  });
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

export const TODAY = '2026-10-09';
export const DAY_URL = `/api/v1/meals/${TODAY}`;

export function renderApp() {
  return render(
    <MealsApp
      labels={labels}
      csrfToken="test-csrf-token"
      languageCode="fr-fr"
      today={TODAY}
      needsUrl="/needs/"
      inventoryUrl="/products/"
    />,
  );
}

export const need = (overrides) => ({
  name: 'Fibres',
  unit: 'g',
  group: 'macronutrient',
  group_label: 'Macronutriment',
  low: '30',
  high: null,
  ends: ['Borne de l’optimisation (anses-2016)'],
  share_low: null,
  share_high: null,
  total: total('12', '10', '14', '100'),
  status: 'below',
  certain: true,
  ...overrides,
});

export const ratio = (overrides) => ({
  numerator: 'Oméga-3',
  denominator: 'Oméga-6',
  molar: false,
  low: '0.9',
  high: '1.1',
  end: 'Votre objectif (user)',
  value: '0.23',
  value_low: '0.2',
  value_high: null,
  status: 'below',
  certain: false,
  ...overrides,
});
