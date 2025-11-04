// Import the pre-built Plotly library ready for use in the browser.
// This package avoids the need to bundle Plotly from source.
// ES6 module
import Plotly from 'plotly.js-dist-min';

// Expose Plotly as a global variable so it can be accessed
// from inline scripts, templates, or other modules (e.g., theme_switcher.js).
window.Plotly = Plotly;

// 🎨 Plotly theme synchronizer for Bootstrap 5 theme switch
function syncPlotlyTheme() {
  const isDark =
    document.documentElement.getAttribute('data-bs-theme') === 'dark';
  const layoutUpdate = {
    template: {
      layout: {
        paper_bgcolor: isDark ? 'rgb(17,17,17)' : 'rgb(255, 255, 255)',
      },
    },
  };

  // Update all existing Plotly charts
  document.querySelectorAll('.js-plotly-plot').forEach((div) => {
    Plotly.relayout(div, layoutUpdate);
  });
}

// 🧩 Observe changes to the <html data-bs-theme="..."> attribute
const observer = new MutationObserver((mutations) => {
  for (const mutation of mutations) {
    if (
      mutation.type === 'attributes' &&
      mutation.attributeName === 'data-bs-theme'
    ) {
      syncPlotlyTheme();
    }
  }
});

observer.observe(document.documentElement, {
  attributes: true,
  attributeFilter: ['data-bs-theme'],
});
