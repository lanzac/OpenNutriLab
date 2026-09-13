// https://albertoroura.com/building-a-theme-switcher-for-bootstrap/
//
// Drives <html data-bs-theme="...">. Plotly charts follow that attribute
// through a MutationObserver (see apps/products/form/plotly-theme.js): the two
// stay decoupled, communicating only through the DOM.

const STORAGE_KEY = 'bs-theme';

function setTheme(mode = 'auto') {
  const userMode = localStorage.getItem(STORAGE_KEY);
  const sysMode = window.matchMedia('(prefers-color-scheme: light)').matches;
  const useSystem = mode === 'system' || (!userMode && mode === 'auto');
  const modeChosen = useSystem
    ? 'system'
    : mode === 'dark' || mode === 'light'
      ? mode
      : userMode;

  if (useSystem) {
    localStorage.removeItem(STORAGE_KEY);
  } else {
    localStorage.setItem(STORAGE_KEY, modeChosen);
  }

  document.documentElement.setAttribute(
    'data-bs-theme',
    useSystem ? (sysMode ? 'light' : 'dark') : modeChosen,
  );
  document
    .querySelectorAll('.mode-switch .btn')
    .forEach((e) => e.classList.remove('text-body'));
  document.getElementById(modeChosen)?.classList.add('text-body');
}

export function initThemeSwitcher() {
  setTheme();
  document
    .querySelectorAll('.mode-switch .btn')
    .forEach((e) => e.addEventListener('click', () => setTheme(e.id)));
  window
    .matchMedia('(prefers-color-scheme: light)')
    .addEventListener('change', () => setTheme());
}
