// Sunburst chart of the macronutrient breakdown, redrawn from the form's
// inputs as they are typed into.
import Plotly from 'plotly.js-strict-dist-min';

const GRAPH_ID = 'macronutrients_graph';
const TOTAL_PERCENTAGE = 100;

// One row per chart slice, in the order sliceValues() below returns them.
// `key` matches Macronutrient.name in the database (see the migration that
// seeds it: products/migrations/0006_alter_macronutrient_labels_and_more.py)
// - except 'others', the chart's own synthetic remainder slice, with no row
// of its own. `parent` is a key from this same list, not display text: the
// displayed label is translated (see initMacronutrientsGraph), so Plotly's
// parent/child structure has to be built from something that stays constant
// across languages.
//
// `field` is the name of the form input holding that slice's amount, as
// ProductForm names it (Macronutrient.name_in_form). 'others' has none: it is
// whatever the top-level slices leave of 100 g.
const SLICES = [
  { key: 'fat', field: 'macronutrients_fat', parent: null, color: '#FF4136' },
  {
    key: 'saturatedFat',
    field: 'macronutrients_saturated_fat',
    parent: 'fat',
    color: '#FF725C',
  },
  {
    key: 'carbohydrates',
    field: 'macronutrients_carbohydrates',
    parent: null,
    color: '#FFDC00',
  },
  {
    key: 'sugars',
    field: 'macronutrients_sugars',
    parent: 'carbohydrates',
    color: '#FFD700',
  },
  {
    key: 'fiber',
    field: 'macronutrients_fiber',
    parent: null,
    color: '#2ECC40',
  },
  {
    key: 'proteins',
    field: 'macronutrients_proteins',
    parent: null,
    color: '#0074D9',
  },
  { key: 'others', field: null, parent: null, color: '#6d6d6dff' },
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
 * Slice values, in SLICES order, for the amounts currently typed in.
 *
 * @param {(field: string) => string | undefined} readField Returns the raw
 *   value of the form input with that name.
 */
export function sliceValues(readField) {
  const amounts = {};
  for (const slice of SLICES) {
    if (slice.field) {
      const amount = Number.parseFloat(readField(slice.field));
      // An empty or unparsable field counts as 0, as it did when the server
      // parsed these values.
      amounts[slice.key] = Number.isFinite(amount) ? amount : 0;
    }
  }

  // Children are part of their parent (saturates are fat), so only the
  // top-level slices count towards the 100 g.
  const used = SLICES.filter((s) => s.field && !s.parent).reduce(
    (sum, s) => sum + amounts[s.key],
    0,
  );

  return SLICES.map((s) =>
    s.field ? amounts[s.key] : Math.max(TOTAL_PERCENTAGE - used, 0),
  );
}

/**
 * @param {Record<string, string>} labels Translated slice labels, see
 *   buildPlotData.
 */
export function initMacronutrientsGraph(labels) {
  const graphDiv = document.getElementById(GRAPH_ID);
  if (!graphDiv) return;

  const form = document.getElementById('product-form');
  const loader = document.getElementById('macronutrients_graph_loader');
  const plotInputs = form.querySelectorAll('.plot-input');
  const plotData = buildPlotData(labels);

  function updatePlot() {
    plotData[0].values = sliceValues(
      (field) => form.querySelector(`[name="${field}"]`)?.value,
    );
    Plotly.react(GRAPH_ID, plotData, plotLayout);
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
