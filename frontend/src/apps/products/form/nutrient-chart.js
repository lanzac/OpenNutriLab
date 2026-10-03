// Sunburst chart of the declared nutrients (per 100 g), redrawn from the
// form's inputs as they are typed into.
import Plotly from 'plotly.js-strict-dist-min';

const GRAPH_ID = 'macronutrients_graph';
const TOTAL_GRAMS = 100;
// The chart's own remainder slice: whatever the top-level slices leave of
// 100 g. It has no nutrient, nor form field, behind it.
const OTHERS = 'others';

// Colours by Nutrient.code. A nutrient added to the catalogue without one
// gets a neutral grey rather than breaking the chart.
const COLORS = {
  fat: '#FF4136',
  saturated_fat: '#FF725C',
  carbohydrates: '#FFDC00',
  sugars: '#FFD700',
  fiber: '#2ECC40',
  proteins: '#0074D9',
  salt: '#B10DC9',
  [OTHERS]: '#6d6d6dff',
};
const DEFAULT_COLOR = '#AAAAAA';

const plotLayout = {
  margin: { l: 0, r: 0, b: 0, t: 0 },
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(0,0,0,0)',
};

/**
 * The chart's slices: one per declared mass nutrient of the catalogue, plus
 * the remainder.
 *
 * Slices are identified and linked to their parent by Nutrient.code, never by
 * the displayed label, which is translated: Plotly's parent/child structure
 * must not depend on the language served.
 *
 * @param {{
 *   slices: { code: string, field: string, parent: string | null, label: string }[],
 *   others: string,
 * }} config From product_form_config in opennutrilab/products/views.py.
 */
export function buildSlices(config) {
  return [
    ...config.slices.map((slice) => ({
      ...slice,
      color: COLORS[slice.code] ?? DEFAULT_COLOR,
    })),
    {
      code: OTHERS,
      field: null,
      parent: null,
      label: config.others,
      color: COLORS[OTHERS],
    },
  ];
}

export function buildPlotData(slices) {
  return [
    {
      type: 'sunburst',
      ids: slices.map((s) => s.code),
      labels: slices.map((s) => s.label),
      parents: slices.map((s) => s.parent ?? ''),
      values: slices.map(() => 0),
      texttemplate: '%{label} (%{value:.2f}%)',
      textinfo: 'text',
      hovertemplate: '%{label}: %{value:.2f}%',
      name: '', // Remove default trace name
      marker: {
        line: { width: 2 },
        colors: slices.map((s) => s.color),
      },
      branchvalues: 'total',
    },
  ];
}

/**
 * Slice values, in `slices` order, for the amounts currently typed in.
 *
 * @param {(field: string) => string | undefined} readField Returns the raw
 *   value of the form input with that name.
 */
export function sliceValues(slices, readField) {
  const amounts = {};
  for (const slice of slices) {
    if (slice.field) {
      const amount = Number.parseFloat(readField(slice.field));
      // An empty or unparsable field counts as 0.
      amounts[slice.code] = Number.isFinite(amount) ? amount : 0;
    }
  }

  // Children are part of their parent (saturates are fat), so only the
  // top-level slices count towards the 100 g.
  const used = slices
    .filter((s) => s.field && !s.parent)
    .reduce((sum, s) => sum + amounts[s.code], 0);

  return slices.map((s) =>
    s.field ? amounts[s.code] : Math.max(TOTAL_GRAMS - used, 0),
  );
}

/**
 * @param {Parameters<typeof buildSlices>[0]} config See buildSlices.
 */
export function initNutrientChart(config) {
  const graphDiv = document.getElementById(GRAPH_ID);
  if (!graphDiv) return;

  const form = document.getElementById('product-form');
  const loader = document.getElementById('macronutrients_graph_loader');
  const plotInputs = form.querySelectorAll('.plot-input');
  const slices = buildSlices(config);
  const plotData = buildPlotData(slices);

  function updatePlot() {
    plotData[0].values = sliceValues(
      slices,
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
