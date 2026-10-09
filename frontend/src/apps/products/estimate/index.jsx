import { createRoot } from 'react-dom/client';

import { EstimatePanel } from './EstimatePanel.jsx';

/**
 * Puts the gauges of the estimate (and the choice between them and the tables) where
 * the page has made room for them. Both are optional: a page with no estimate has
 * neither, and a failed estimate has no data.
 *
 * @param {{ labels: Record<string, string>, languageCode: string }} config From
 *   product_form_config in opennutrilab/products/views.py.
 */
export function initEstimatePanel(config) {
  const container = document.getElementById('estimate-view');
  const script = document.getElementById('estimate-panel');
  if (!container || !script) return;

  createRoot(container).render(
    <EstimatePanel
      data={JSON.parse(script.textContent)}
      labels={config.labels}
      languageCode={config.languageCode}
      tables={[...document.querySelectorAll('#estimate [data-estimate-table]')]}
    />,
  );
}
