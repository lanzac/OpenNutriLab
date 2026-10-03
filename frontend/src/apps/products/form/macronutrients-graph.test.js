import { describe, expect, it } from 'vitest';

import { buildPlotData, sliceValues } from './macronutrients-graph.js';

// Stands in for product_form_labels()["macronutrientsGraph"] in
// opennutrilab/products/views.py - real French text, so a regression back to the
// hardcoded English keys fails these tests the same way
// ProductListApp.test.jsx catches it for the product list.
const LABELS = {
  fat: 'Matières grasses',
  saturatedFat: 'dont graisses saturées',
  carbohydrates: 'Glucides',
  sugars: 'dont sucres',
  fiber: 'Fibres',
  proteins: 'Protéines',
  others: 'Autres',
};

describe('buildPlotData', () => {
  it('labels every slice with the translated text, not the internal key', () => {
    const [trace] = buildPlotData(LABELS);

    expect(trace.labels).toEqual([
      'Matières grasses',
      'dont graisses saturées',
      'Glucides',
      'dont sucres',
      'Fibres',
      'Protéines',
      'Autres',
    ]);
  });

  it('keeps the parent/child structure keyed by id, unaffected by translation', () => {
    const [enTrace] = buildPlotData({
      fat: 'Fat',
      saturatedFat: 'Saturated Fat',
      carbohydrates: 'Carbohydrates',
      sugars: 'Sugars',
      fiber: 'Fiber',
      proteins: 'Proteins',
      others: 'Others',
    });
    const [frTrace] = buildPlotData(LABELS);

    // Regression guard for a real bug: parents used to reference the English
    // display text directly ('Fat', 'Carbohydrates'), which would have
    // silently detached every child slice from its parent in any other
    // language, since Plotly matches parents by id/label and no translated
    // label would ever equal that hardcoded English parent string.
    expect(enTrace.ids).toEqual(frTrace.ids);
    expect(enTrace.parents).toEqual(frTrace.parents);
    expect(frTrace.parents).toEqual([
      '',
      'fat',
      '',
      'carbohydrates',
      '',
      '',
      '',
    ]);
  });

  it('assigns a defined color to every slice', () => {
    const [trace] = buildPlotData(LABELS);

    // Regression guard for a real bug: colours used to be keyed by a display
    // string ('Saturated Fat (of which)') that never matched the label
    // actually in use ('Saturated Fat'), so that slice - and the sugars one
    // - rendered with an undefined (Plotly-default) colour instead of the
    // intended one.
    expect(trace.marker.colors).toHaveLength(trace.ids.length);
    trace.marker.colors.forEach((color) => expect(color).toBeTruthy());
  });
});

describe('sliceValues', () => {
  const read = (values) => (field) => values[field];

  it('reads each slice from its form field, in SLICES order', () => {
    const values = sliceValues(
      read({
        macronutrients_fat: '10.5',
        macronutrients_saturated_fat: '3',
        macronutrients_carbohydrates: '50',
        macronutrients_sugars: '20',
        macronutrients_fiber: '5',
        macronutrients_proteins: '15',
      }),
    );

    // others = 100 - (fat + carbohydrates + fiber + proteins): children are
    // already inside their parent and must not be counted twice.
    expect(values).toEqual([10.5, 3, 50, 20, 5, 15, 19.5]);
  });

  it('counts empty, missing and unparsable fields as 0', () => {
    const values = sliceValues(
      read({ macronutrients_fat: '', macronutrients_proteins: 'abc' }),
    );

    expect(values).toEqual([0, 0, 0, 0, 0, 0, 100]);
  });

  it('never makes the remainder negative', () => {
    const values = sliceValues(
      read({ macronutrients_fat: '80', macronutrients_proteins: '40' }),
    );

    expect(values.at(-1)).toBe(0);
  });
});
