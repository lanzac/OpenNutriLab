// Entry point for the product create/edit form (see
// opennutrilab/templates/products/product_form.html).
//
// Vanilla DOM code driving the server-rendered (crispy-forms) form: the
// barcode picture, the lookup and the search of OpenFoodFacts, the groups of nutrients,
// the macronutrient chart and the ingredients tree; and, on the estimate, the
// gauges (React, see estimate/).
import { initEstimatePanel } from './estimate/index.jsx';
import { initBarcodeImage } from './form/barcode-image.jsx';
import { initFoldableGroups } from './form/foldable-groups.js';
import { initIngredientsTable } from './form/ingredients-table.js';
import { initIngredientsText } from './form/ingredients-text.js';
import { initOffLookup } from './form/off-lookup.js';
import { initNutrientChart } from './form/nutrient-chart.js';
import { initOffSearch } from './form/off-search.js';
import { initPlotlyTheme } from './form/plotly-theme.js';

// Modules are deferred, so the document may already be parsed.
function ready(callback) {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', callback);
  } else {
    callback();
  }
}

ready(() => {
  // Built and translated server-side (see product_form_config in
  // opennutrilab/products/views.py), handed over the same way ProductListView
  // does for the React list.
  const config = JSON.parse(
    document.getElementById('product-form-config').textContent,
  );

  initBarcodeImage(config.barcodeImage);
  initFoldableGroups();
  initPlotlyTheme();
  initNutrientChart(config.nutrientChart);
  const ingredients = initIngredientsTable(config.ingredientsTable);
  // The text the ingredients were read from, read again without the places a
  // person left out, or corrected: the table shows the new reading.
  const text = initIngredientsText({
    onRead: (reading) => ingredients?.setRows(reading.rows),
    config: config.ingredientsText,
  });
  // What OpenFoodFacts has for the barcode, set against the form: typed in, or
  // chosen from a search.
  const lookup = initOffLookup(config.offLookup, text);
  initOffSearch(config.offSearch, { onChoose: lookup?.lookup });
  initEstimatePanel(config.estimatePanel);
});
