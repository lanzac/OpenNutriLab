// Entry point for the product create/edit form (see
// opennutrilab/templates/products/product_form.html).
//
// Vanilla DOM code driving the server-rendered (crispy-forms) form: the
// barcode buttons, the macronutrient chart and the ingredients tree.
import { initBarcodeActions } from './form/barcode-actions.js';
import { initIngredientsTable } from './form/ingredients-table.js';
import { initNutrientChart } from './form/nutrient-chart.js';
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

  initBarcodeActions(config.barcodeActions);
  initPlotlyTheme();
  initNutrientChart(config.nutrientChart);
  initIngredientsTable(config.ingredientsTable);
});
