import { createRoot } from 'react-dom/client';

import { ProductListApp } from './ProductListApp.jsx';

const container = document.getElementById('product-list-root');

if (container) {
  createRoot(container).render(<ProductListApp />);
}
