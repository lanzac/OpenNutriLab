// Keeps Plotly charts in step with the Bootstrap 5 theme switcher, which
// flips <html data-bs-theme="...">.
import Plotly from 'plotly.js-strict-dist-min';

const DARK_PAPER_BG = 'rgb(17,17,17)';
const LIGHT_PAPER_BG = 'rgb(255, 255, 255)';

function syncPlotlyTheme() {
  const isDark =
    document.documentElement.getAttribute('data-bs-theme') === 'dark';
  const layoutUpdate = {
    template: {
      layout: { paper_bgcolor: isDark ? DARK_PAPER_BG : LIGHT_PAPER_BG },
    },
  };

  document.querySelectorAll('.js-plotly-plot').forEach((div) => {
    Plotly.relayout(div, layoutUpdate);
  });
}

export function initPlotlyTheme() {
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
}
