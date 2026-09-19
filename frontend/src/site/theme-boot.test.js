import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { afterEach, describe, expect, it, vi } from 'vitest';

import { initThemeSwitcher, STORAGE_KEY } from './theme-switcher.js';

// The inline boot script in <head> duplicates the theme resolution on purpose:
// it runs before any bundle exists, so it cannot import this module. These
// tests are what keeps the copy honest - change one side's rules and they fail.
const TEMPLATE = resolve(
  import.meta.dirname,
  '../../../opennutrilab/templates/components/theme_boot.html',
);

function bootSnippet() {
  const html = readFileSync(TEMPLATE, 'utf8');
  const match = html.match(/<script>([\s\S]*?)<\/script>/);
  if (!match) {
    throw new Error(`no inline <script> found in ${TEMPLATE}`);
  }
  return match[1];
}

function stubEnvironment(stored, systemPrefersLight) {
  localStorage.clear();
  if (stored !== null) {
    localStorage.setItem(STORAGE_KEY, stored);
  }
  vi.stubGlobal('matchMedia', (query) => ({
    media: query,
    matches: query.includes('light') ? systemPrefersLight : !systemPrefersLight,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
  document.documentElement.removeAttribute('data-bs-theme');
}

function themeAfter(run) {
  run();
  return document.documentElement.getAttribute('data-bs-theme');
}

// Every combination the first paint can land in.
const CASES = [
  { stored: 'dark', systemPrefersLight: true },
  { stored: 'dark', systemPrefersLight: false },
  { stored: 'light', systemPrefersLight: true },
  { stored: 'light', systemPrefersLight: false },
  { stored: null, systemPrefersLight: true },
  { stored: null, systemPrefersLight: false },
];

describe('the inline theme boot script', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it.each(CASES)(
    'agrees with the theme switcher (stored=$stored, system light=$systemPrefersLight)',
    ({ stored, systemPrefersLight }) => {
      const snippet = bootSnippet();

      stubEnvironment(stored, systemPrefersLight);
      const fromBoot = themeAfter(() => new Function(snippet)());

      // Re-stub: the switcher rewrites storage on the way through, and the
      // boot script must be compared against a pristine starting point.
      stubEnvironment(stored, systemPrefersLight);
      const fromSwitcher = themeAfter(initThemeSwitcher);

      expect(fromBoot).toBe(fromSwitcher);
      expect(fromBoot).not.toBeNull();
    },
  );

  it('reads the same storage key as the switcher', () => {
    expect(bootSnippet()).toContain(`'${STORAGE_KEY}'`);
  });

  it('survives storage being unreadable', () => {
    vi.stubGlobal('matchMedia', () => ({ matches: false }));
    vi.stubGlobal('localStorage', {
      getItem() {
        throw new Error('storage blocked');
      },
    });
    document.documentElement.removeAttribute('data-bs-theme');

    new Function(bootSnippet())();

    // Falls back to the system preference rather than leaving it unset, which
    // would put the page back on Bootstrap's light default.
    expect(document.documentElement.getAttribute('data-bs-theme')).toBe('dark');
  });
});
