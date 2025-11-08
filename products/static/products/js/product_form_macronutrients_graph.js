// Need to check why this script located in products/static/products/js/
// is not transpiled (I think?) by webpack

// Script called in opennutrilab/templates/products/product_form.html
window.addEventListener('DOMContentLoaded', () => {
  const loader = document.getElementById('macronutrients_graph_loader');
  const plotInputs = document.querySelectorAll('#product-form .plot-input');
  const graphDiv = document.getElementById('macronutrients_graph');
  if (graphDiv) {
    const labelColors = {
      Total: '#ffffffff',
      Fat: '#FF4136',
      'Saturated Fat (of which)': '#FF725C',
      Carbohydrates: '#FFDC00',
      'Sugars (of which)': '#FFD700',
      Fiber: '#2ECC40',
      Proteins: '#0074D9',
      Others: '#6d6d6dff',
    };
    const labels = [
      'Fat',
      'Saturated Fat',
      'Carbohydrates',
      'Sugars',
      'Fiber',
      'Proteins',
      'Others',
    ];
    const parents = ['', 'Fat', '', 'Carbohydrates', '', '', ''];
    const colors = labels.map((label) => labelColors[label]);
    var plot_data = [
      {
        type: 'sunburst',
        labels: labels,
        parents: parents,
        values: [0, 0, 0, 0, 0, 0],
        texttemplate: '%{label} (%{value:.2f}%)',
        textinfo: 'text',
        hovertemplate: '%{label}: %{value:.2f}%',
        name: '', // Remove default trace name
        marker: { line: { width: 2 }, colors: colors },
        branchvalues: 'total',
      },
    ];

    var plot_layout = {
      margin: { l: 0, r: 0, b: 0, t: 0 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
    };

    Plotly.newPlot('macronutrients_graph', plot_data, plot_layout, {
      displayModeBar: false,
      responsive: true,
    }).then(() => {
      if (loader) {
        loader.style.display = 'none';
      }
      updatePlot();
    });
  }

  async function updatePlot() {
    const formData = new FormData();

    plotInputs.forEach((input) => {
      const value = input.value?.trim();
      formData.append(input.name, value === '' || value == null ? 0 : value);
    });

    const params = new URLSearchParams(formData);
    const apiUrl = window.CONFIG.macronutrientsApiUrl;

    if (!apiUrl) {
      console.error('API URL not found in window.CONFIG');
      return;
    }

    try {
      const response = await fetch(apiUrl + '?' + params.toString());
      if (!response.ok) throw new Error('network error');

      const newData = await response.json();
      const macronutrients = newData?.macronutrients;

      if (!macronutrients) {
        console.warn('No macronutrient data found in response:', newData);
        return; // nothing to update
      }

      const {
        fat = 0,
        saturated_fat = 0,
        carbohydrates = 0,
        sugars = 0,
        fiber = 0,
        proteins = 0,
      } = macronutrients;

      const TOTAL_PERCENTAGE = 100;
      const used = fat + carbohydrates + fiber + proteins;
      const remaining = Math.max(TOTAL_PERCENTAGE - used, 0);

      plot_data[0].values = [
        fat,
        saturated_fat,
        carbohydrates,
        sugars,
        fiber,
        proteins,
        remaining,
      ];

      Plotly.react('macronutrients_graph', plot_data, plot_layout);
    } catch (error) {
      console.error('Failed to update macronutrients graph:', error);
    }
  }

  plotInputs.forEach((input) => {
    input.addEventListener('input', updatePlot);
  });
});
