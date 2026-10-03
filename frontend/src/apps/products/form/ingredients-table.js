// Collapsible ingredients tree on the product form, rendered by Tabulator
// from the rows the view serialises into the page (#ingredients-data).
import { TabulatorFull as Tabulator } from 'tabulator-tables';

import 'tabulator-tables/dist/css/tabulator_bootstrap5.min.css';

/**
 * Content of a CIQUAL cell: the code as a link to its sheet on the CIQUAL
 * site, or nothing when the ingredient has no code. Built with the DOM API so
 * a code is never read as HTML.
 *
 * @param {string | null | undefined} label The code as shown, e.g. "9410 (proxy)".
 * @param {string | null | undefined} url Where its sheet is, from the view.
 * @returns {HTMLAnchorElement | string}
 */
export function ciqualCell(label, url) {
  if (!url) return '';
  const link = document.createElement('a');
  link.href = url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.textContent = label ?? '';
  return link;
}

/**
 * @param {{ name: string, percentage: string, ciqual: string, reference: string }} labels
 *   Column titles, translated server-side (see product_form_config in
 *   opennutrilab/products/views.py) so the .po catalogue stays the single
 *   source of truth.
 */
export function initIngredientsTable(labels) {
  const tableDiv = document.getElementById('ingredients_table');
  if (!tableDiv) return;

  const loader = document.getElementById('ingredients_graph_loader');
  // An array of rows, or nothing at all when the form has no ingredients yet
  // (a new product that was not fetched from OpenFoodFacts).
  const rows = JSON.parse(
    document.getElementById('ingredients-data').textContent,
  );
  const ingredientsData = Array.isArray(rows) ? rows : [];

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
      // As OpenFoodFacts gives it, for information: it links no reference
      // ingredient, but opens the code's sheet on the CIQUAL site to check it.
      {
        title: labels.ciqual,
        field: 'ciqual',
        responsive: 3,
        formatter: (cell) =>
          ciqualCell(cell.getValue(), cell.getRow().getData().ciqual_url),
      },
      // The curated reference ingredient, once one is linked by hand.
      { title: labels.reference, field: 'reference', responsive: 3 },
    ],
    dataTreeChildField: 'ingredients',
  });

  if (loader) loader.style.display = 'none';
}
