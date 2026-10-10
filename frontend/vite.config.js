import { resolve } from 'node:path';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The name under which a browser reaches this machine, "localhost" unless the
// site is opened from another one. Same variable as config/settings/local.py,
// which has the page point the browser at this server under that name.
const devHost = process.env.DEV_HOST || 'localhost';

// One build entry per page bundle, plus the site-wide shell and its separate
// stylesheet entry. base.html and the page templates load them through
// django-vite's {% vite_asset %} / {% vite_asset_url %} tags.
export default defineConfig({
  plugins: [react()],
  // Matches STATIC_URL + DJANGO_VITE.static_url_prefix in config/settings/base.py
  base: '/static/vite/',
  build: {
    manifest: true,
    outDir: resolve(import.meta.dirname, '../opennutrilab/static/vite'),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        // Site-wide shell: loaded by base.html on every page.
        site: resolve(import.meta.dirname, 'src/site/site-entry.js'),
        // CSS-only entry, loaded through its own <link> tag rather than the
        // 'site' entry above. See src/site/styles/site-styles.scss for why:
        // it is what keeps the dev server from injecting this CSS via JS,
        // which is what caused the load flash.
        'site-styles': resolve(
          import.meta.dirname,
          'src/site/styles/site-styles.scss',
        ),
        'products-list': resolve(
          import.meta.dirname,
          'src/apps/products/list-entry.jsx',
        ),
        'products-form': resolve(
          import.meta.dirname,
          'src/apps/products/form-entry.js',
        ),
        meals: resolve(import.meta.dirname, 'src/apps/meals/meals-entry.jsx'),
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    // Vite answers 403 to any Host header it does not know.
    allowedHosts: [devHost],
    // The page, served by Django on :8000, loads the modules from here, so
    // Vite has to send the CORS header to it. Setting `cors` replaces Vite's
    // default, which only answers pages served from localhost, hence the
    // first entry being that same pattern.
    cors: {
      origin: [
        /^https?:\/\/(?:(?:[^:]+\.)?localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$/,
        `http://${devHost}:8000`,
      ],
    },
    origin: `http://${devHost}:5173`,
  },
  test: {
    environment: 'jsdom',
    setupFiles: './vitest.setup.js',
    globals: true,
  },
});
