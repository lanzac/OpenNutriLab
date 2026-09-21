// Collapsible ingredients tree on the product form. Ported from
// products/static/products/js/product_form_ingredients_table.js, previously
// served raw through {% static %}.
//
// Tabulator used to arrive as a global set by tabulator_loader.js; it is
// imported directly now, along with its stylesheet.
import { TabulatorFull as Tabulator } from 'tabulator-tables';

import 'tabulator-tables/dist/css/tabulator_bootstrap5.min.css';
import './tabulator.scss';

/**
 * @param {{ name: string, percentage: string, recognized: string }} labels
 *   Column titles, translated server-side (see product_form_labels in
 *   products/views.py) so the .po catalogue stays the single source of truth.
 */
export function initIngredientsTable(labels) {
  const tableDiv = document.getElementById('ingredients_table');
  if (!tableDiv) return;

  const loader = document.getElementById('ingredients_graph_loader');
  const ingredientsData = JSON.parse(
    document.getElementById('ingredients-data').textContent,
  );

  new Tabulator('#ingredients_table', {
    height: '311px',
    data: ingredientsData,
    dataTree: true,
    dataTreeCollapseElement: "<i class='fas fa-minus-square'></i>", //fontawesome toggle icon
    dataTreeExpandElement: "<i class='fas fa-plus-square'></i>", //fontawesome toggle icon
    dataTreeStartExpanded: false,
    columns: [
      { title: labels.name, field: 'name', responsive: 0 }, //never hide this column
      {
        title: labels.percentage,
        field: 'percentage',
        responsive: 2,
        formatter: function (cell) {
          const value = cell.getValue();
          return value !== null && value !== undefined
            ? Number(value).toFixed(2) + ' %'
            : '';
        },
      },
      {
        title: labels.recognized,
        field: 'has_reference',
        hozAlign: 'center',
        formatter: 'tickCross',
      },
    ],
    dataTreeChildField: 'ingredients',
  });

  if (loader) loader.style.display = 'none';
}
