import { describe, expect, it } from 'vitest';

import { buildPlotData, buildSlices, sliceValues } from './nutrient-chart.js';

// Stands in for product_form_config()["nutrientChart"] in
// opennutrilab/products/views.py, with the French names the catalogue holds.
const CONFIG = {
  slices: [
    {
      code: 'fat',
      field: 'nutrient_fat',
      parent: null,
      label: 'Matières grasses',
    },
    {
      code: 'saturated_fat',
      field: 'nutrient_saturated_fat',
      parent: 'fat',
      label: 'dont acides gras saturés',
    },
    {
      code: 'carbohydrates',
      field: 'nutrient_carbohydrates',
      parent: null,
      label: 'Glucides',
    },
    {
      code: 'sugars',
      field: 'nutrient_sugars',
      parent: 'carbohydrates',
      label: 'dont sucres',
    },
    {
      code: 'fiber',
      field: 'nutrient_fiber',
      parent: null,
      label: 'Fibres alimentaires',
    },
    {
      code: 'proteins',
      field: 'nutrient_proteins',
      parent: null,
      label: 'Protéines',
    },
    { code: 'salt', field: 'nutrient_salt', parent: null, label: 'Sel' },
  ],
  others: 'Autres',
};

describe('buildSlices', () => {
  it('follows the catalogue and appends the remainder slice', () => {
    const slices = buildSlices(CONFIG);

    expect(slices.map((s) => s.code)).toEqual([
      'fat',
      'saturated_fat',
      'carbohydrates',
      'sugars',
      'fiber',
      'proteins',
      'salt',
      'others',
    ]);
    expect(slices.at(-1)).toMatchObject({ field: null, label: 'Autres' });
  });

  it('gives a nutrient the chart has no colour for a default one', () => {
    const slices = buildSlices({
      slices: [
        {
          code: 'polyols',
          field: 'nutrient_polyols',
          parent: null,
          label: 'Polyols',
        },
      ],
      others: 'Autres',
    });

    slices.forEach((slice) => expect(slice.color).toBeTruthy());
  });
});

describe('buildPlotData', () => {
  it('labels every slice with the translated text, not the code', () => {
    const [trace] = buildPlotData(buildSlices(CONFIG));

    expect(trace.labels).toEqual([
      'Matières grasses',
      'dont acides gras saturés',
      'Glucides',
      'dont sucres',
      'Fibres alimentaires',
      'Protéines',
      'Sel',
      'Autres',
    ]);
  });

  it('links children to parents by code, unaffected by translation', () => {
    // Regression guard: parents once referenced the English display text,
    // which detached every child slice in any other language.
    const [trace] = buildPlotData(buildSlices(CONFIG));

    expect(trace.parents).toEqual([
      '',
      'fat',
      '',
      'carbohydrates',
      '',
      '',
      '',
      '',
    ]);
    expect(trace.ids).toContain('fat');
  });
});

describe('sliceValues', () => {
  const slices = buildSlices(CONFIG);
  const read = (values) => (field) => values[field];

  it('reads each slice from its form field, in slice order', () => {
    const values = sliceValues(
      slices,
      read({
        nutrient_fat: '10.5',
        nutrient_saturated_fat: '3',
        nutrient_carbohydrates: '50',
        nutrient_sugars: '20',
        nutrient_fiber: '5',
        nutrient_proteins: '15',
        nutrient_salt: '1.5',
      }),
    );

    // others = 100 - (fat + carbohydrates + fiber + proteins + salt): children
    // are already inside their parent and must not be counted twice.
    expect(values).toEqual([10.5, 3, 50, 20, 5, 15, 1.5, 18]);
  });

  it('counts empty, missing and unparsable fields as 0', () => {
    const values = sliceValues(
      slices,
      read({ nutrient_fat: '', nutrient_proteins: 'abc' }),
    );

    expect(values).toEqual([0, 0, 0, 0, 0, 0, 0, 100]);
  });

  it('never makes the remainder negative', () => {
    const values = sliceValues(
      slices,
      read({ nutrient_fat: '80', nutrient_proteins: '40' }),
    );

    expect(values.at(-1)).toBe(0);
  });
});
