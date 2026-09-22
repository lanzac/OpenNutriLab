// Site-wide bundle: what every page needs, loaded by base.html.
//
// JS only. The stylesheet is a separate Vite entry (./styles/site-styles.scss),
// loaded by base.html through its own <link> tag rather than an import here -
// see that file for why. This module still needs to run for the theme
// switcher and Bootstrap's interactive behaviour.
//
// Bootstrap's JS is imported for its side effects (navbar collapse, alert
// dismissal, dropdowns); it brings @popperjs/core along.
import 'bootstrap';

import { initThemeSwitcher } from './theme-switcher.js';

initThemeSwitcher();
