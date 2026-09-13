import { createRoot } from 'react-dom/client';

import { ProductListApp } from './ProductListApp.jsx';

const container = document.getElementById('product-list-root');
const propsScript = document.getElementById('product-list-props');

if (container && propsScript) {
  const props = JSON.parse(propsScript.textContent);
  createRoot(container).render(<ProductListApp {...props} />);
}
