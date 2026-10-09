import { createRoot } from 'react-dom/client';

import { MealsApp } from './MealsApp.jsx';

const container = document.getElementById('meals-root');
const propsScript = document.getElementById('meals-props');

if (container && propsScript) {
  const props = JSON.parse(propsScript.textContent);
  createRoot(container).render(<MealsApp {...props} />);
}
