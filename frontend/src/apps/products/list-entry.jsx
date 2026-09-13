import { createRoot } from 'react-dom/client';

import { ProductListApp } from './ProductListApp.jsx';

const container = document.getElementById('product-list-root');
const labelsScript = document.getElementById('product-list-labels');

if (container && labelsScript) {
  const labels = JSON.parse(labelsScript.textContent);
  createRoot(container).render(<ProductListApp labels={labels} />);
}
