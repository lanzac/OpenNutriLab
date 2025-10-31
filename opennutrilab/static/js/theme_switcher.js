// https://mdbootstrap.com/docs/standard/extended/bootstrap-dark-mode-switch/#
// Theme switcher logic for Bootstrap 5 (using data-bs-theme)
const themeSwitcher = document.getElementById('themingSwitcher');

// Detect if system prefers dark mode
const isSystemThemeSetToDark = window.matchMedia(
  '(prefers-color-scheme: dark)',
).matches;

// Load saved theme from localStorage or fallback to system preference
const savedTheme = localStorage.getItem('theme');
const currentTheme = savedTheme || (isSystemThemeSetToDark ? 'dark' : 'light');

// Apply theme to the <html> element
document.documentElement.dataset.bsTheme = currentTheme;

// Set the toggle switch position based on the current theme
if (themeSwitcher) {
  themeSwitcher.checked = currentTheme === 'dark';

  // Listen for switch changes
  themeSwitcher.addEventListener('change', (e) => {
    toggleTheme(e.target.checked);
  });
}

// Function to toggle between light and dark themes
function toggleTheme(isChecked) {
  const theme = isChecked ? 'dark' : 'light';
  document.documentElement.dataset.bsTheme = theme;
  localStorage.setItem('theme', theme);
}

// Keyboard shortcut: Shift + D toggles the theme
document.addEventListener('keydown', (e) => {
  if (e.shiftKey && e.key.toLowerCase() === 'd') {
    if (themeSwitcher) {
      themeSwitcher.checked = !themeSwitcher.checked;
      toggleTheme(themeSwitcher.checked);
    }
  }
});
