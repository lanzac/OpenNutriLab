import { resolve } from 'node:path';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// This config is intentionally scoped to the products area for now. Entries
// are added incrementally as pages move over (see the migration plan). The
// global site bundle (nav, Bootstrap, theme switcher) stays on the existing
// Webpack pipeline until the final cutover.
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
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    origin: 'http://localhost:5173',
  },
  test: {
    environment: 'jsdom',
    setupFiles: './vitest.setup.js',
    globals: true,
  },
});
