import { resolve } from 'node:path';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// This config is intentionally scoped to the products/inventory area for now.
// Entries are added incrementally as more of the app is ported to React
// (see the migration plan). The global site bundle (nav, Bootstrap, theme
// switcher) stays on the existing Webpack pipeline until the final cutover.
export default defineConfig({
  plugins: [react()],
  // Matches STATIC_URL + DJANGO_VITE.static_url_prefix in config/settings/base.py
  base: '/static/vite/',
  build: {
    manifest: true,
    outDir: resolve(__dirname, '../opennutrilab/static/vite'),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        'products-list': resolve(
          __dirname,
          'src/apps/products/list-entry.jsx',
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
