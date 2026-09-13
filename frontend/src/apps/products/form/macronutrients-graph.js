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

const LABEL_COLORS = {
  Total: '#ffffffff',
  Fat: '#FF4136',
  'Saturated Fat (of which)': '#FF725C',
  Carbohydrates: '#FFDC00',
  'Sugars (of which)': '#FFD700',
  Fiber: '#2ECC40',
  Proteins: '#0074D9',
  Others: '#6d6d6dff',
};

// TODO(i18n): these labels reach the user untranslated; the .po catalogue
// already carries most of them.
const LABELS = [
  'Fat',
  'Saturated Fat',
  'Carbohydrates',
  'Sugars',
  'Fiber',
  'Proteins',
  'Others',
];
const PARENTS = ['', 'Fat', '', 'Carbohydrates', '', '', ''];

const plotLayout = {
  margin: { l: 0, r: 0, b: 0, t: 0 },
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(0,0,0,0)',
};

function buildPlotData() {
  return [
    {
      type: 'sunburst',
      labels: LABELS,
      parents: PARENTS,
      values: [0, 0, 0, 0, 0, 0],
      texttemplate: '%{label} (%{value:.2f}%)',
      textinfo: 'text',
      hovertemplate: '%{label}: %{value:.2f}%',
      name: '', // Remove default trace name
      marker: {
        line: { width: 2 },
        colors: LABELS.map((l) => LABEL_COLORS[l]),
      },
      branchvalues: 'total',
    },
  ];
}

export function initMacronutrientsGraph() {
  const graphDiv = document.getElementById(GRAPH_ID);
  if (!graphDiv) return;

  const loader = document.getElementById('macronutrients_graph_loader');
  const plotInputs = document.querySelectorAll('#product-form .plot-input');
  const plotData = buildPlotData();

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
