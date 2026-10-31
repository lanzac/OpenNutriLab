import { vi } from 'vitest';

// What the inventory tests share: the French catalogue entries ProductListView gives
// (so a regression back to hardcoded English in the JSX fails them), a few products
// as the API serves them, and a stand-in for fetch.

export const labels = {
  barcode: 'Code barre',
  uncategorised: 'Non classé',
  createdAt: 'Créé le',
  loading: 'Chargement…',
  loadError: 'Échec du chargement des produits.',
  confirmDelete: 'Supprimer « %(name)s » ?',
  myInventory: 'Mon inventaire',
  allProducts: 'Tous les produits',
  addToInventory: 'Ajouter à mon inventaire',
  removeFromInventory: 'Retirer de mon inventaire',
  inventoryEmpty:
    'Votre inventaire est vide. Affichez tous les produits pour en ajouter.',
  inventoryError: "Votre inventaire n'a pas pu être modifié.",
  packageOfServings: '%(count)s %(noun)s de %(serving)s',
  stock: 'Stock',
  stockUnit: 'Unité du stock',
  stockServings: 'portions',
  stockNotCounted: 'Non compté',
  stockUsedUp: 'Épuisé',
  stockAddPackage: 'Ajouter un paquet (%(package)s) au stock',
  stockSaveError: "Le stock n'a pas pu être enregistré.",
  stockInStock: 'en stock',
  stockNotCountedRow: 'Stock non compté',
  inInventory: 'Dans mon inventaire',
  stockCountedOn: 'Compté le %(date)s',
  stockRemoveOne: 'Un de moins : %(noun)s',
  stockAddOne: 'Un de plus : %(noun)s',
  stockPackage: 'paquet',
  stockEquivalent: 'Soit %(amount)s.',
  stockNotCountedHint:
    "Non compté : rien ne limite les repas, et rien n'est retiré.",
  stockCountIn: 'Compter en',
  stockOnePackage: 'Un paquet · %(package)s',
  stockMarkUsedUp: 'Marquer épuisé',
  stockEatenNote: "Les repas marqués « mangés » retirent du stock d'eux-mêmes.",
  searchProducts: 'Rechercher un produit',
  filterByStock: 'Filtrer selon le stock',
  filterAll: 'Tous',
  filterInStock: 'En stock',
  filterUsedUp: 'Épuisés',
  filterNotCounted: 'Non comptés',
  noMatch: 'Aucun produit ne correspond.',
  inventory: 'Inventaire',
  productSheet: 'Fiche du produit',
  panelEmpty: 'Choisissez un produit pour voir sa fiche et compter son stock.',
  theProduct: 'Le produit',
  package: 'Conditionnement',
  serving: 'Portion',
  openSheet: 'Ouvrir la fiche complète',
  openSheetHint:
    'Ingrédients, valeurs nutritionnelles, estimation des nutriments.',
  removeFromInventoryHint:
    'Le produit reste dans le catalogue, et son stock est oublié.',
  adminZone: 'Administrateur',
  deleteFromCatalogue: 'Supprimer du catalogue…',
  deleteFromCatalogueHint: 'Le produit disparaît pour tous les utilisateurs.',
};

// What ProductListView gives: the words the groups are stored with, in French.
export const groupNames = {
  'Cereals and potatoes': 'Céréales et pommes de terre',
  Cereals: 'Céréales',
  'Breakfast cereals': 'Céréales du petit-déjeuner',
  'Fish Meat Eggs': 'Viandes, poissons et œufs',
};

export const CSRF_TOKEN = 'test-csrf-token';
export const PLACEHOLDER = '/static/images/milk-carton.png';

// A rice in a package of 1000 g, in the inventory and not counted.
export const RICE = {
  barcode: '4006381333931',
  name: 'Rice',
  image: '/media/images/products/4006381333931.jpg',
  group_level_1: 'Cereals and potatoes',
  group_level_2: 'Cereals',
  package: { quantity: '1000.00', unit: 'g' },
  serving: null,
  count_noun: null,
  created_at: '2026-01-01T00:00:00Z',
  in_inventory: true,
  stock: { quantity: null, unit: 'g', counted_at: null },
};

// Oats, which are in the catalogue and not in the inventory.
export const OATS = {
  barcode: '3229820794556',
  name: 'Oats',
  image: null,
  group_level_1: 'Cereals and potatoes',
  group_level_2: 'Breakfast cereals',
  package: null,
  serving: null,
  count_noun: null,
  created_at: '2026-01-02T00:00:00Z',
  in_inventory: false,
  stock: null,
};

// A muesli in grams: its serving has no name that is a thing.
export const MUESLI = {
  barcode: '3017620422003',
  name: 'Muesli',
  image: null,
  group_level_1: 'Cereals and potatoes',
  group_level_2: 'Breakfast cereals',
  package: { quantity: '375.00', unit: 'g' },
  serving: { quantity: '30.00', unit: 'g', name: '' },
  count_noun: null,
  created_at: '2026-01-03T00:00:00Z',
  in_inventory: true,
  stock: { quantity: '300.00', unit: 'g', counted_at: '2026-10-10T12:00:00Z' },
};

// A compote in pots of 100 g: counted by pot, which are whole.
export const COMPOTE = {
  ...MUESLI,
  barcode: '3245412890987',
  name: 'Compote',
  package: { quantity: '400.00', unit: 'g' },
  serving: { quantity: '100.00', unit: 'g', name: '1 pot' },
  count_noun: 'pot',
  stock: {
    quantity: '4.00',
    unit: 'serving',
    counted_at: '2026-10-10T12:00:00Z',
  },
};

/**
 * A fetch that answers `answers`, by "METHOD url" (a GET by its url alone), and
 * throws for a call it was not told of.
 */
export function stubFetch(answers) {
  const fetch = vi.fn((url, init = {}) => {
    const key = `${init.method ?? 'GET'} ${url}`;
    if (!(key in answers)) throw new Error(`unexpected ${key}`);
    const answer = answers[key];
    if (answer instanceof Error) {
      return Promise.resolve({ ok: false, status: 500 });
    }
    return Promise.resolve({ ok: true, json: async () => answer });
  });
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

export const PRODUCTS_URL = 'GET /api/v1/products/';
