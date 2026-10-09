import { describe, expect, it } from 'vitest';

import { groupProducts } from './groups.js';

const options = {
  names: { 'Fish Meat Eggs': 'Viandes, poissons et œufs', Meat: 'Viandes' },
  uncategorised: 'Non classé',
  locale: 'fr-fr',
};

const product = (name, group_level_1, group_level_2) => ({
  name,
  group_level_1,
  group_level_2,
});

describe('groupProducts', () => {
  it('names the groups with the words it is given, and as stored where it has none', () => {
    const groups = groupProducts(
      [
        product('Steak', 'Fish Meat Eggs', 'Meat'),
        product('Tofu', 'Plant based', 'Soy'),
      ],
      options,
    );

    expect(groups.map((g) => g.name)).toEqual([
      'Plant based',
      'Viandes, poissons et œufs',
    ]);
    expect(groups[1].subgroups[0].name).toBe('Viandes');
    expect(groups[0].subgroups[0].name).toBe('Soy');
  });

  it('puts the products of no group, or of "unknown", last in a group of their own', () => {
    const groups = groupProducts(
      [
        product('A', 'unknown', 'unknown'),
        product('B', 'Unknown', ''),
        product('C', undefined, undefined),
        product('D', null, null),
        product('Z', 'Zebra', 'Stripes'),
      ],
      options,
    );

    expect(groups.map((g) => [g.name, g.count])).toEqual([
      ['Zebra', 1],
      ['Non classé', 4],
    ]);
  });

  it('titles the subgroups only for a group that has a known one', () => {
    const [cereals, meat] = groupProducts(
      [
        product('Steak', 'Fish Meat Eggs', 'Meat'),
        product('Ham', 'Fish Meat Eggs', ''),
        product('Rice', 'Cereals', 'unknown'),
      ],
      options,
    );

    // By the name shown: "Cereals" is before "Viandes, poissons et œufs".
    expect(cereals.name).toBe('Cereals');
    expect(cereals.titled).toBe(false);
    expect(meat.titled).toBe(true);
    // The subgroup with no name is the last of its group.
    expect(meat.subgroups.map((s) => s.name)).toEqual([
      'Viandes',
      'Non classé',
    ]);
  });

  it('sorts by the rules of the language, and the products by name', () => {
    const [group] = groupProducts(
      [
        product('Zucchini', 'Veg', 'Raw'),
        product('Écrevisse', 'Veg', 'Raw'),
        product('Eau', 'Veg', 'Raw'),
      ],
      options,
    );

    expect(group.subgroups[0].products.map((p) => p.name)).toEqual([
      'Eau',
      'Écrevisse',
      'Zucchini',
    ]);
  });

  it('cuts an empty list into no group', () => {
    expect(groupProducts([], options)).toEqual([]);
  });
});
