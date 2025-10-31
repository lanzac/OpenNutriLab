import '../sass/project.scss';
import './fouc_helper.js';
import './theme_switcher.js';

/* Project specific Javascript goes here. */

// https://mdbootstrap.com/docs/standard/extended/bootstrap-dark-mode-switch/#
// Theme switcher logic for Bootstrap 5 (using data-bs-theme)
// Load saved theme from localStorage, or use system preference
const savedTheme = localStorage.getItem('theme');
const isSystemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
const theme = savedTheme || (isSystemDark ? 'dark' : 'light');

// Apply the chosen theme immediately to the <html> element
document.documentElement.dataset.bsTheme = theme;
