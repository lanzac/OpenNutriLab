// Sunburst chart of the macronutrient breakdown, refreshed as the form is
// typed into. Ported from products/static/products/js/
// product_form_macronutrients_graph.js, which was served raw through
// {% static %} and so never went through any build step - hence the comment
// it carried wondering why it was not transpiled.
//
// Plotly used to arrive as a global set by plotly_loader.js; it is imported
// directly now.
import Plotly from 'plotly.js-strict-dist-min';

const GRAPH_ID = 'macronutrients_graph';
const TOTAL_PERCENTAGE = 100;

// One row per chart slice, in the order updatePlot() below fills `values`.
// `key` matches Macronutrient.name in the database (see the migration that
// seeds it: products/migrations/0006_alter_macronutrient_labels_and_more.py)
// - except 'others', the chart's own synthetic remainder slice, with no row
// of its own. `parent` is a key from this same list, not display text: the
// displayed label is translated (see initMacronutrientsGraph), so Plotly's
// parent/child structure has to be built from something that stays constant
// across languages.
const SLICES = [
  { key: 'fat', parent: null, color: '#FF4136' },
  { key: 'saturatedFat', parent: 'fat', color: '#FF725C' },
  { key: 'carbohydrates', parent: null, color: '#FFDC00' },
  { key: 'sugars', parent: 'carbohydrates', color: '#FFD700' },
  { key: 'fiber', parent: null, color: '#2ECC40' },
  { key: 'proteins', parent: null, color: '#0074D9' },
  { key: 'others', parent: null, color: '#6d6d6dff' },
];

const plotLayout = {
  margin: { l: 0, r: 0, b: 0, t: 0 },
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(0,0,0,0)',
};

/**
 * @param {Record<string, string>} labels Translated display text keyed like
 *   SLICES (see product_form_labels in products/views.py).
 */
export function buildPlotData(labels) {
  return [
    {
      type: 'sunburst',
      ids: SLICES.map((s) => s.key),
      labels: SLICES.map((s) => labels[s.key]),
      parents: SLICES.map((s) => s.parent ?? ''),
      values: SLICES.map(() => 0),
      texttemplate: '%{label} (%{value:.2f}%)',
      textinfo: 'text',
      hovertemplate: '%{label}: %{value:.2f}%',
      name: '', // Remove default trace name
      marker: {
        line: { width: 2 },
        colors: SLICES.map((s) => s.color),
      },
      branchvalues: 'total',
    },
  ];
}

/**
 * @param {Record<string, string>} labels Translated slice labels, see
 *   buildPlotData.
 */
export function initMacronutrientsGraph(labels) {
  const graphDiv = document.getElementById(GRAPH_ID);
  if (!graphDiv) return;

  const loader = document.getElementById('macronutrients_graph_loader');
  const plotInputs = document.querySelectorAll('#product-form .plot-input');
  const plotData = buildPlotData(labels);

  async function updatePlot() {
    const formData = new FormData();
    plotInputs.forEach((input) => {
      const value = input.value?.trim();
      formData.append(input.name, value === '' || value == null ? 0 : value);
    });

    const apiUrl = window.CONFIG?.macronutrientsApiUrl;
    if (!apiUrl) {
      console.error('API URL not found in window.CONFIG');
      return;
    }

    try {
      const params = new URLSearchParams(formData);
      const response = await fetch(`${apiUrl}?${params.toString()}`);
      if (!response.ok) throw new Error('network error');

      const macronutrients = (await response.json())?.macronutrients;
      if (!macronutrients) return;

      const {
        fat = 0,
        saturated_fat = 0,
        carbohydrates = 0,
        sugars = 0,
        fiber = 0,
        proteins = 0,
      } = macronutrients;
      const used = fat + carbohydrates + fiber + proteins;

      plotData[0].values = [
        fat,
        saturated_fat,
        carbohydrates,
        sugars,
        fiber,
        proteins,
        Math.max(TOTAL_PERCENTAGE - used, 0),
      ];

      Plotly.react(GRAPH_ID, plotData, plotLayout);
    } catch (error) {
      console.error('Failed to update macronutrients graph:', error);
    }
  }

  Plotly.newPlot(GRAPH_ID, plotData, plotLayout, {
    displayModeBar: false,
    responsive: true,
  }).then(() => {
    if (loader) loader.style.display = 'none';
    updatePlot();
  });

  plotInputs.forEach((input) => input.addEventListener('input', updatePlot));
}
