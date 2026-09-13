import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ProductListApp } from './ProductListApp.jsx';

// Stands in for the |json_script blob rendered by ProductListView. Values are
// the real French catalogue entries, so a regression back to hardcoded English
// in the JSX fails these tests.
const labels = {
  productName: 'Nom du produit',
  createdAt: 'Créé le',
  actions: 'Actions',
  edit: 'Éditer',
  delete: 'Supprimer',
  editAndDelete: 'Éditer et Supprimer un produit',
  loading: 'Chargement…',
  loadError: 'Échec du chargement des produits.',
  confirmDelete: 'Supprimer « %(name)s » ?',
};

const RICE = {
  barcode: '1234567890123',
  name: 'Rice',
  created_at: '2026-01-01T00:00:00Z',
};

function stubFetchSuccess(products = [RICE]) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: async () => products }),
  );
}

const CSRF_TOKEN = 'test-csrf-token';

function renderList() {
  return render(
    <ProductListApp
      labels={labels}
      csrfToken={CSRF_TOKEN}
      languageCode="fr-fr"
    />,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('ProductListApp', () => {
  it('renders products fetched from the API', async () => {
    stubFetchSuccess();
    renderList();

    await waitFor(() => expect(screen.getByText('Rice')).toBeInTheDocument());
    expect(screen.getByRole('link', { name: /Éditer/ })).toHaveAttribute(
      'href',
      '/products/1234567890123/edit/',
    );
  });

  it('labels the table from the supplied translations', async () => {
    stubFetchSuccess();
    renderList();

    await waitFor(() =>
      expect(
        screen.getByRole('columnheader', { name: 'Nom du produit' }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByRole('columnheader', { name: 'Créé le' }),
    ).toBeInTheDocument();
    // Restores the aria-label the first React port dropped.
    expect(
      screen.getByRole('toolbar', { name: 'Éditer et Supprimer un produit' }),
    ).toBeInTheDocument();
  });

  it('interpolates the product name into the delete confirmation', async () => {
    stubFetchSuccess();
    // Returning false keeps jsdom from attempting a real form submission.
    const confirm = vi.fn().mockReturnValue(false);
    vi.stubGlobal('confirm', confirm);
    renderList();

    await waitFor(() => expect(screen.getByText('Rice')).toBeInTheDocument());
    screen.getByRole('button', { name: /Supprimer/ }).click();

    expect(confirm).toHaveBeenCalledWith('Supprimer « Rice » ?');
  });

  it('puts the server-supplied CSRF token on the delete form', async () => {
    // CSRF_COOKIE_HTTPONLY hides the token from document.cookie, so reading it
    // client-side yields an empty string and every delete POST 403s.
    stubFetchSuccess();
    renderList();

    await waitFor(() => expect(screen.getByText('Rice')).toBeInTheDocument());
    const field = document.querySelector('[name="csrfmiddlewaretoken"]');
    expect(field).not.toBeNull();
    expect(field.value).toBe(CSRF_TOKEN);
  });

  it('formats dates with the language Django is serving', async () => {
    // Without an explicit locale, Intl falls back to the runtime's, which is
    // unrelated to the language Django negotiated for the page.
    stubFetchSuccess();
    renderList();

    await waitFor(() => expect(screen.getByText('Rice')).toBeInTheDocument());
    expect(screen.getByText('01/01/2026')).toBeInTheDocument();
  });

  it('renders nothing when the inventory is empty', async () => {
    stubFetchSuccess([]);
    renderList();

    await waitFor(() => expect(screen.queryByRole('table')).toBeNull());
  });

  it('shows a translated error message when the fetch fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 500 }),
    );
    const consoleError = vi
      .spyOn(console, 'error')
      .mockImplementation(() => {});
    renderList();

    await waitFor(() =>
      expect(
        screen.getByText('Échec du chargement des produits.'),
      ).toBeInTheDocument(),
    );
    // The HTTP status stays in the console, out of the user's face.
    expect(consoleError).toHaveBeenCalled();
  });
});
