// Entry point for the product create/edit form (see
// opennutrilab/templates/products/product_form.html).
//
// Vanilla DOM code driving the server-rendered (crispy-forms) form: the
// barcode buttons, the macronutrient chart and the ingredients tree.
import { initBarcodeActions } from './form/barcode-actions.js';
import { initIngredientsTable } from './form/ingredients-table.js';
import { initMacronutrientsGraph } from './form/macronutrients-graph.js';
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
  // Translated server-side (see product_form_labels in products/views.py),
  // handed over the same way ProductListView does for the React list.
  const labels = JSON.parse(
    document.getElementById('product-form-labels').textContent,
  );

  initBarcodeActions(labels.barcodeActions);
  initPlotlyTheme();
  initMacronutrientsGraph(labels.macronutrientsGraph);
  initIngredientsTable(labels.ingredientsTable);
});
