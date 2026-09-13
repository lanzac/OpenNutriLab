// Entry point for the product create/edit form (see
// opennutrilab/templates/products/product_form.html).
//
// Replaces three webpack bundles - fetch_barcode, plotly_loader,
// tabulator_loader - plus the two scripts that used to be served raw through
// {% static %}. Vanilla DOM code for now: this is a build-pipeline move, not
// a React port.
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
  initBarcodeActions();
  initPlotlyTheme();
  initMacronutrientsGraph();
  initIngredientsTable();
});
