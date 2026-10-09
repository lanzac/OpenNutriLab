import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ProductListApp } from './ProductListApp.jsx';

// Stands in for the |json_script blob rendered by ProductListView. Values are
// the real French catalogue entries, so a regression back to hardcoded English
// in the JSX fails these tests.
const labels = {
  productName: 'Nom du produit',
  totalQuantity: 'Quantité totale',
  createdAt: 'Créé le',
  actions: 'Actions',
  edit: 'Éditer',
  delete: 'Supprimer',
  editAndDelete: 'Éditer et Supprimer un produit',
  loading: 'Chargement…',
  loadError: 'Échec du chargement des produits.',
  confirmDelete: 'Supprimer « %(name)s » ?',
  myInventory: 'Mon inventaire',
  allProducts: 'Tous les produits',
  addToInventory: 'Ajouter à mon inventaire',
  removeFromInventory: 'Retirer de mon inventaire',
  inventoryEmpty:
    'Votre inventaire est vide. Affichez tous les produits pour en ajouter.',
  inventoryError: "Votre inventaire n'a pas pu être modifié.",
};

const RICE = {
  barcode: '1234567890123',
  name: 'Rice',
  package: { quantity: '1000.00', unit: 'g' },
  created_at: '2026-01-01T00:00:00Z',
  in_inventory: true,
};

const OATS = {
  barcode: '3229820794556',
  name: 'Oats',
  package: null,
  created_at: '2026-01-02T00:00:00Z',
  in_inventory: false,
};

function stubFetchSuccess(products = [RICE]) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: async () => products }),
  );
}

const CSRF_TOKEN = 'test-csrf-token';

function renderList({ canDelete = true } = {}) {
  return render(
    <ProductListApp
      labels={labels}
      csrfToken={CSRF_TOKEN}
      languageCode="fr-fr"
      canDelete={canDelete}
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

  it('shows the total quantity of a product, and nothing where it has none', async () => {
    stubFetchSuccess([RICE, { ...OATS, in_inventory: true }]);
    renderList();

    await waitFor(() => expect(screen.getByText('Rice')).toBeInTheDocument());

    expect(
      screen.getByRole('columnheader', { name: 'Quantité totale' }),
    ).toBeInTheDocument();
    const rows = screen.getAllByRole('row');
    expect(
      within(rows[1]).getByRole('cell', { name: /1\s000 g/ }),
    ).toBeInTheDocument();
    // The cell is there for the columns to line up, and empty.
    expect(within(rows[2]).getAllByRole('cell')[1]).toBeEmptyDOMElement();
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

  it('offers no delete button to users who may not delete', async () => {
    // Deleting is reserved to staff server-side; the list must not offer a
    // button that can only end in a 403.
    stubFetchSuccess();
    renderList({ canDelete: false });

    await waitFor(() => expect(screen.getByText('Rice')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /Supprimer/ })).toBeNull();
    expect(screen.getByRole('link', { name: /Éditer/ })).toBeInTheDocument();
  });

  it('formats dates with the language Django is serving', async () => {
    // Without an explicit locale, Intl falls back to the runtime's, which is
    // unrelated to the language Django negotiated for the page.
    stubFetchSuccess();
    renderList();

    await waitFor(() => expect(screen.getByText('Rice')).toBeInTheDocument());
    expect(screen.getByText('01/01/2026')).toBeInTheDocument();
  });

  it('renders nothing when there is no product at all', async () => {
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

  it("shows the user's inventory first, and every product on request", async () => {
    stubFetchSuccess([RICE, OATS]);
    renderList();

    await waitFor(() => expect(screen.getByText('Rice')).toBeInTheDocument());
    expect(screen.queryByText('Oats')).toBeNull();
    expect(
      screen.getByRole('button', { name: 'Mon inventaire' }),
    ).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(screen.getByRole('button', { name: 'Tous les produits' }));

    expect(screen.getByText('Oats')).toBeInTheDocument();
    expect(screen.getByText('Rice')).toBeInTheDocument();
  });

  it('says how to fill an empty inventory', async () => {
    stubFetchSuccess([OATS]);
    renderList();

    await waitFor(() =>
      expect(
        screen.getByText(
          'Votre inventaire est vide. Affichez tous les produits pour en ajouter.',
        ),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('puts a product in the inventory with the CSRF token', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => [RICE, OATS] })
      .mockResolvedValueOnce({ ok: true, json: async () => ({}) });
    vi.stubGlobal('fetch', fetch);
    renderList();
    await waitFor(() => expect(screen.getByText('Rice')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Tous les produits' }));

    fireEvent.click(
      screen.getByRole('button', { name: /Ajouter à mon inventaire/ }),
    );

    await waitFor(() =>
      expect(
        screen.getAllByRole('button', { name: /Retirer de mon inventaire/ }),
      ).toHaveLength(2),
    );
    expect(fetch).toHaveBeenLastCalledWith('/api/v1/inventory/3229820794556', {
      method: 'PUT',
      headers: { Accept: 'application/json', 'X-CSRFToken': CSRF_TOKEN },
    });
  });

  it('takes a product out of the inventory, and it leaves the list', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => [RICE] })
      .mockResolvedValueOnce({ ok: true, json: async () => ({}) });
    vi.stubGlobal('fetch', fetch);
    renderList();
    await waitFor(() => expect(screen.getByText('Rice')).toBeInTheDocument());

    fireEvent.click(
      screen.getByRole('button', { name: /Retirer de mon inventaire/ }),
    );

    await waitFor(() => expect(screen.queryByText('Rice')).toBeNull());
    expect(fetch).toHaveBeenLastCalledWith(
      '/api/v1/inventory/1234567890123',
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('says so when the inventory cannot be changed', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce({ ok: true, json: async () => [RICE] })
        .mockResolvedValueOnce({ ok: false, status: 403 }),
    );
    vi.spyOn(console, 'error').mockImplementation(() => {});
    renderList();
    await waitFor(() => expect(screen.getByText('Rice')).toBeInTheDocument());

    fireEvent.click(
      screen.getByRole('button', { name: /Retirer de mon inventaire/ }),
    );

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(
        "Votre inventaire n'a pas pu être modifié.",
      ),
    );
    expect(screen.getByText('Rice')).toBeInTheDocument();
  });
});
