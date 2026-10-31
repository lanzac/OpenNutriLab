import { describe, expect, it } from 'vitest';

import {
  convertStock,
  defaultStockUnit,
  describeAmount,
  describeEquivalent,
  describePackage,
  describeStock,
  packageAddition,
  packageContent,
  packageServings,
  plural,
  stockStatus,
  stockUnitOptions,
} from './stockUnits.js';

const labels = {
  packageOfServings: '%(count)s %(noun)s de %(serving)s',
  stockServings: 'portions',
  stockPackage: 'paquet',
  stockEquivalent: 'Soit %(amount)s.',
};

const COMPOTE = {
  name: 'Compote',
  count_noun: 'pot',
  package: { quantity: '400.00', unit: 'g' },
  serving: { quantity: '100.00', unit: 'g', name: '1 pot' },
};
const BREAD = {
  name: 'Pain',
  count_noun: 'tranche',
  package: { quantity: '500.00', unit: 'g' },
  serving: { quantity: '35.70', unit: 'g', name: '1 tranche' },
};
const PASTA = {
  name: 'girandole 34',
  count_noun: null,
  package: { quantity: '1000.00', unit: 'g' },
  serving: { quantity: '80.00', unit: 'g', name: '' },
};
const OIL = {
  name: 'Huile',
  count_noun: null,
  package: { quantity: '1000.00', unit: 'ml' },
  serving: { quantity: '12.00', unit: 'g', name: '1 cs' },
};

describe('plural', () => {
  it.each([
    ['pot', 1, 'pot'],
    ['pot', 0, 'pot'],
    ['pot', 4, 'pots'],
    ['tranche', 14, 'tranches'],
    ['tranche de pain', 3, 'tranches de pain'],
    ['gâteau', 2, 'gâteaux'],
    ['noix', 2, 'noix'],
    ['oeuf', 6, 'oeufs'],
  ])('writes %s for %s as %s', (noun, count, expected) => {
    expect(plural(noun, count)).toBe(expected);
  });
});

describe('packageServings', () => {
  it('counts the servings a package holds', () => {
    expect(packageServings(COMPOTE)).toBe(4);
    expect(
      packageServings({ ...COMPOTE, package: { quantity: '1200', unit: 'g' } }),
    ).toBe(12);
  });

  it('takes 500 g of bread in slices of 35.7 g for 14 slices', () => {
    expect(packageServings(BREAD)).toBe(14);
  });

  it('is null where the package is not a whole number of servings', () => {
    const muesli = {
      package: { quantity: '375', unit: 'g' },
      serving: { quantity: '30', unit: 'g' },
    };
    expect(packageServings(muesli)).toBeNull();
  });

  it('is null with no package, no serving, or other units', () => {
    expect(packageServings({ ...COMPOTE, package: null })).toBeNull();
    expect(packageServings({ ...COMPOTE, serving: null })).toBeNull();
    expect(packageServings(OIL)).toBeNull();
  });

  it('is null for a package smaller than a serving', () => {
    expect(
      packageServings({
        package: { quantity: '50', unit: 'g' },
        serving: { quantity: '100', unit: 'g' },
      }),
    ).toBeNull();
  });
});

describe('packageContent', () => {
  it('is the package in grams or millilitres where the stock is in that unit', () => {
    expect(packageContent(COMPOTE, 'g')).toBe(400);
    expect(packageContent(OIL, 'ml')).toBe(1000);
  });

  it('is the servings it holds where the stock is in servings', () => {
    expect(packageContent(COMPOTE, 'serving')).toBe(4);
  });

  it('is null where the units differ or the package is not whole servings', () => {
    expect(packageContent(OIL, 'g')).toBeNull();
    expect(packageContent(PASTA, 'serving')).toBeNull();
    expect(packageContent({ ...COMPOTE, package: null }, 'g')).toBeNull();
  });
});

describe('convertStock', () => {
  it('turns grams into the pots they need, a started pot being a pot', () => {
    expect(convertStock(400, 'g', 'serving', COMPOTE)).toBe(4);
    expect(convertStock(450, 'g', 'serving', COMPOTE)).toBe(5);
    expect(convertStock(30, 'g', 'serving', COMPOTE)).toBe(1);
  });

  it('turns pots into grams', () => {
    expect(convertStock(3, 'serving', 'g', COMPOTE)).toBe(300);
    expect(convertStock(3, 'serving', 'g', BREAD)).toBe(107.1);
  });

  it('keeps a quantity in its own unit', () => {
    expect(convertStock(7, 'g', 'g', COMPOTE)).toBe(7);
  });

  it('is null where the units cannot be told apart', () => {
    expect(convertStock(5, 'ml', 'serving', COMPOTE)).toBeNull();
    expect(convertStock(5, 'g', 'ml', COMPOTE)).toBeNull();
    expect(
      convertStock(5, 'g', 'serving', { ...COMPOTE, serving: null }),
    ).toBeNull();
  });
});

describe('stockUnitOptions', () => {
  it('offers grams and pots for a product counted by pot', () => {
    expect(stockUnitOptions(COMPOTE, 'serving', null, labels)).toEqual([
      { value: 'g', label: 'g' },
      { value: 'serving', label: 'pots' },
    ]);
  });

  it('offers grams only for the pasta, which has no serving to count by', () => {
    expect(stockUnitOptions(PASTA, 'g', null, labels)).toEqual([
      { value: 'g', label: 'g' },
    ]);
  });

  it('offers the millilitres of an oil, whatever its serving', () => {
    expect(stockUnitOptions(OIL, 'ml', 250, labels)).toEqual([
      { value: 'ml', label: 'ml' },
    ]);
  });

  it('keeps the unit a stock is counted in, even if the product no longer offers it', () => {
    expect(
      stockUnitOptions(PASTA, 'serving', null, labels).map((o) => o.value),
    ).toContain('serving');
  });

  it('offers only the units a counted stock can be brought to', () => {
    const odd = {
      ...COMPOTE,
      serving: { quantity: '100', unit: 'ml', name: '1 pot' },
    };
    expect(stockUnitOptions(odd, 'g', 400, labels).map((o) => o.value)).toEqual(
      ['g'],
    );
  });
});

describe('describePackage', () => {
  it('says a package of pots as pots', () => {
    expect(describePackage(COMPOTE, labels, 'fr-fr')).toBe('4 pots de 100 g');
  });

  it('says a single thing in the singular', () => {
    const sachet = {
      count_noun: 'sachet',
      package: { quantity: '220', unit: 'g' },
      serving: { quantity: '220', unit: 'g', name: '1 sachet' },
    };
    expect(describePackage(sachet, labels, 'fr-fr')).toBe('1 sachet de 220 g');
  });

  it('writes the weight of a slice with its decimals', () => {
    expect(describePackage(BREAD, labels, 'fr-fr')).toMatch(
      /^14 tranches de 35,7 g$/,
    );
  });

  it('keeps grams for a product whose serving is not a thing', () => {
    expect(describePackage(PASTA, labels, 'fr-fr')).toMatch(/^1\s?000 g$/);
  });

  it('keeps the package where it is not a whole number of servings', () => {
    const muesli = {
      count_noun: 'bol',
      package: { quantity: '375', unit: 'g' },
      serving: { quantity: '30', unit: 'g', name: '1 bol' },
    };
    expect(describePackage(muesli, labels, 'fr-fr')).toBe('375 g');
  });

  it('says nothing for a product with no package', () => {
    expect(
      describePackage({ ...COMPOTE, package: null }, labels, 'fr-fr'),
    ).toBe('');
  });
});

describe('defaultStockUnit', () => {
  it('is the servings for a product counted by a thing, else the unit of the package', () => {
    expect(defaultStockUnit(COMPOTE)).toBe('serving');
    expect(defaultStockUnit(PASTA)).toBe('g');
    expect(
      defaultStockUnit({
        count_noun: null,
        package: { quantity: '1', unit: 'ml' },
      }),
    ).toBe('ml');
    expect(defaultStockUnit({ count_noun: null, package: null })).toBe('g');
  });
});

describe('stockStatus', () => {
  const held = (quantity, unit = 'g') => ({
    in_inventory: true,
    stock: { quantity, unit },
  });

  it('is nothing for a product that is not in the inventory', () => {
    expect(stockStatus({ in_inventory: false, stock: null })).toBeNull();
  });

  it('tells a stock not counted from one used up, which is nothing', () => {
    expect(stockStatus(held(null))).toBe('uncounted');
    expect(stockStatus({ in_inventory: true })).toBe('uncounted');
    expect(stockStatus(held('0.00'))).toBe('used-up');
    expect(stockStatus(held('0.5'))).toBe('counted');
  });
});

describe('describeAmount', () => {
  it('writes things with their noun, in the plural from two', () => {
    expect(describeAmount(COMPOTE, 'serving', 1, labels, 'fr-fr')).toBe(
      '1 pot',
    );
    expect(describeAmount(COMPOTE, 'serving', 3, labels, 'fr-fr')).toBe(
      '3 pots',
    );
  });

  it('writes a weight with its unit, and servings with no noun as servings', () => {
    expect(describeAmount(PASTA, 'g', 270, labels, 'fr-fr')).toBe('270 g');
    expect(describeAmount(PASTA, 'serving', 2, labels, 'fr-fr')).toBe(
      '2 portions',
    );
  });
});

describe('describeStock', () => {
  it('writes the stock of a product in the unit it is counted in', () => {
    const stocked = {
      ...COMPOTE,
      stock: { quantity: '3.00', unit: 'serving' },
    };
    expect(describeStock(stocked, labels, 'fr-fr')).toBe('3 pots');
  });
});

describe('packageAddition', () => {
  it('adds what a package holds to the stock, in the unit it is counted in', () => {
    const stocked = {
      ...COMPOTE,
      stock: { quantity: '4.00', unit: 'serving' },
    };
    expect(packageAddition(stocked, labels, 'fr-fr')).toEqual({
      unit: 'serving',
      quantity: 8,
      text: '4 pots',
    });
  });

  it('starts from nothing where the stock is not counted, in the default unit', () => {
    const addition = packageAddition(
      { ...PASTA, stock: null },
      labels,
      'fr-fr',
    );

    expect(addition).toMatchObject({ unit: 'g', quantity: 1000 });
    // The thousands are separated by a space that does not break, which `\s` takes.
    expect(addition.text).toMatch(/^1\s000 g$/);
  });

  it('has nothing to add where the package is not known in that unit', () => {
    expect(
      packageAddition({ ...PASTA, package: null }, labels, 'fr-fr'),
    ).toBeNull();
    expect(
      packageAddition(
        { ...PASTA, stock: { quantity: '2', unit: 'ml' } },
        labels,
        'fr-fr',
      ),
    ).toBeNull();
  });

  it('adds without float dust', () => {
    const dust = {
      ...PASTA,
      package: { quantity: '0.1', unit: 'g' },
      stock: { quantity: '0.20', unit: 'g' },
    };
    expect(packageAddition(dust, labels, 'fr-fr').quantity).toBe(0.3);
  });
});

describe('describeEquivalent', () => {
  it('gives the weight of pots and the share of a package they make', () => {
    expect(describeEquivalent(COMPOTE, 'serving', 2, labels, 'fr-fr')).toBe(
      'Soit 200 g, 0,5 paquet.',
    );
    expect(describeEquivalent(COMPOTE, 'serving', 8, labels, 'fr-fr')).toBe(
      'Soit 800 g, 2 paquets.',
    );
  });

  it('gives only the share of a package for a weight', () => {
    expect(describeEquivalent(PASTA, 'g', 250, labels, 'fr-fr')).toBe(
      'Soit 0,25 paquet.',
    );
  });

  it('says nothing where it has nothing to add, or nothing is counted', () => {
    expect(
      describeEquivalent(
        { ...PASTA, package: null },
        'g',
        250,
        labels,
        'fr-fr',
      ),
    ).toBe('');
    expect(describeEquivalent(PASTA, 'g', null, labels, 'fr-fr')).toBe('');
    // A stock used up is nothing in any terms.
    expect(describeEquivalent(PASTA, 'g', 0, labels, 'fr-fr')).toBe('');
  });
});
