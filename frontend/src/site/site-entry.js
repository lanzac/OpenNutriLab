// Site-wide bundle: what every page needs. Replaces the webpack 'project' and
// 'vendors' entries that base.html used to pull in through {% render_bundle %}.
//
// Bootstrap's JS is imported for its side effects (navbar collapse, alert
// dismissal, dropdowns); it brings @popperjs/core along.
import 'bootstrap';

// Vendor stylesheets. Imported here rather than from project.scss so Vite
// rewrites their font and flag asset URLs; the webpack build reached them
// through the '~' prefix, which Vite does not support.
import '@fortawesome/fontawesome-free/css/all.css';
import 'bootstrap-icons/font/bootstrap-icons.css';
import 'flag-icons/css/flag-icons.min.css';

import './styles/project.scss';

import { initFouc } from './fouc.js';
import { initThemeSwitcher } from './theme-switcher.js';

initThemeSwitcher();
initFouc();
