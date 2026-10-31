import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  COMPOTE,
  CSRF_TOKEN,
  groupNames,
  labels,
  MUESLI,
  OATS,
  PLACEHOLDER,
  PRODUCTS_URL,
  RICE,
  stubFetch,
} from './fixtures.js';
import { ProductListApp } from './ProductListApp.jsx';

function renderList({ canDelete = true } = {}) {
  return render(
    <ProductListApp
      labels={labels}
      groupNames={groupNames}
      csrfToken={CSRF_TOKEN}
      languageCode="fr-fr"
      canDelete={canDelete}
      placeholderImage={PLACEHOLDER}
    />,
  );
}

const USED_UP = { ...MUESLI, stock: { ...MUESLI.stock, quantity: '0.00' } };

const click = (name) => fireEvent.click(screen.getByRole('button', { name }));
const rowOf = (name) => screen.getByRole('button', { name }).closest('li');
const sheet = () =>
  screen.getByRole('complementary', { name: 'Fiche du produit' });

/** The names of the lines, in the order the list shows them. */
const names = () =>
  [...document.querySelectorAll('.inventory-row-main button')].map(
    (button) => button.textContent,
  );

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.history.replaceState(null, '', '/');
});

describe('ProductListApp', () => {
  it('renders products fetched from the API, with what a package holds', async () => {
    stubFetch({ [PRODUCTS_URL]: [RICE] });
    renderList();

    expect(await screen.findByRole('button', { name: 'Rice' })).toBeVisible();
    expect(within(rowOf('Rice')).getByText(/1\s000 g/)).toBeInTheDocument();
  });

  it("shows each product's photo, or the placeholder where it has none", async () => {
    stubFetch({ [PRODUCTS_URL]: [RICE, { ...OATS, in_inventory: true }] });
    renderList();
    await screen.findByRole('button', { name: 'Rice' });

    expect(rowOf('Rice').querySelector('img')).toHaveAttribute(
      'src',
      '/media/images/products/4006381333931.jpg',
    );
    expect(rowOf('Oats').querySelector('img')).toHaveAttribute(
      'src',
      PLACEHOLDER,
    );
  });

  it('renders nothing when there is no product at all', async () => {
    stubFetch({ [PRODUCTS_URL]: [] });
    const { container } = renderList();

    await waitFor(() => expect(screen.queryByText('Chargement…')).toBeNull());
    expect(container).toBeEmptyDOMElement();
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

    expect(
      await screen.findByText('Échec du chargement des produits.'),
    ).toBeInTheDocument();
    // The HTTP status stays in the console, out of the user's face.
    expect(consoleError).toHaveBeenCalled();
  });
});

describe('ProductListApp, the stock on the line', () => {
  it('says where the stock of each product stands', async () => {
    stubFetch({ [PRODUCTS_URL]: [COMPOTE, RICE, USED_UP] });
    renderList();
    await screen.findByRole('button', { name: 'Compote' });

    const compote = within(rowOf('Compote'));
    expect(compote.getByText('4 pots')).toBeInTheDocument();
    expect(compote.getByText('en stock')).toBeInTheDocument();
    expect(
      within(rowOf('Rice')).getByText('Stock non compté'),
    ).toBeInTheDocument();
    expect(within(rowOf('Muesli')).getByText('Épuisé')).toBeInTheDocument();
  });

  it('writes the total of a package of pots as pots, and of one in grams as grams', async () => {
    stubFetch({ [PRODUCTS_URL]: [COMPOTE, MUESLI] });
    renderList();

    expect(await screen.findByText('4 pots de 100 g')).toBeInTheDocument();
    expect(screen.getByText('375 g')).toBeInTheDocument();
  });

  it('adds a package from the line, and shows what the server holds', async () => {
    const fetch = stubFetch({
      [PRODUCTS_URL]: [MUESLI],
      [`PUT /api/v1/inventory/${MUESLI.barcode}/stock`]: {
        barcode: MUESLI.barcode,
        stock: { quantity: '675.00', unit: 'g', counted_at: null },
      },
    });
    renderList();
    await screen.findByRole('button', { name: 'Muesli' });

    click('Ajouter un paquet (375 g) au stock – Muesli');

    expect(await within(rowOf('Muesli')).findByText('675 g')).toBeVisible();
    expect(fetch).toHaveBeenCalledWith(
      `/api/v1/inventory/${MUESLI.barcode}/stock`,
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ quantity: 675, unit: 'g' }),
        headers: expect.objectContaining({ 'X-CSRFToken': CSRF_TOKEN }),
      }),
    );
  });

  it('says so when a package could not be added', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    stubFetch({
      [PRODUCTS_URL]: [MUESLI],
      [`PUT /api/v1/inventory/${MUESLI.barcode}/stock`]: new Error('500'),
    });
    renderList();
    await screen.findByRole('button', { name: 'Muesli' });

    click('Ajouter un paquet (375 g) au stock – Muesli');

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "Le stock n'a pas pu être enregistré.",
    );
  });

  it('has no package to add for a product that has none', async () => {
    stubFetch({ [PRODUCTS_URL]: [{ ...RICE, package: null }] });
    renderList();
    await screen.findByRole('button', { name: 'Rice' });

    expect(
      screen.queryByRole('button', { name: /Ajouter un paquet/ }),
    ).toBeNull();
  });

  it('offers to take a product that is used up out of the inventory, from its line', async () => {
    const fetch = stubFetch({
      [PRODUCTS_URL]: [USED_UP, RICE],
      [`DELETE /api/v1/inventory/${MUESLI.barcode}`]: {},
    });
    renderList();
    await screen.findByRole('button', { name: 'Muesli' });
    // Only for the one that is used up.
    expect(
      screen.getAllByRole('button', { name: 'Retirer de mon inventaire' }),
    ).toHaveLength(1);

    fireEvent.click(
      within(rowOf('Muesli')).getByRole('button', {
        name: 'Retirer de mon inventaire',
      }),
    );

    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Muesli' })).toBeNull(),
    );
    expect(fetch).toHaveBeenLastCalledWith(
      `/api/v1/inventory/${MUESLI.barcode}`,
      expect.objectContaining({ method: 'DELETE' }),
    );
  });
});

describe('ProductListApp, the sheet of a product', () => {
  it('says to choose a product while none is open', async () => {
    stubFetch({ [PRODUCTS_URL]: [RICE] });
    renderList();
    await screen.findByRole('button', { name: 'Rice' });

    expect(
      screen.getByText(
        'Choisissez un produit pour voir sa fiche et compter son stock.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole('complementary')).toBeNull();
  });

  it('opens from the line, with the product in full', async () => {
    stubFetch({ [PRODUCTS_URL]: [{ ...COMPOTE, group_level_2: 'Cereals' }] });
    renderList();
    await screen.findByRole('button', { name: 'Compote' });

    click('Compote');

    const panel = within(sheet());
    expect(
      panel.getByRole('heading', { level: 2, name: 'Compote' }),
    ).toBeInTheDocument();
    expect(
      panel.getByText('Céréales et pommes de terre › Céréales'),
    ).toBeInTheDocument();
    expect(panel.getByText('4 pots de 100 g')).toBeInTheDocument();
    expect(panel.getByText('1 pot (100 g)')).toBeInTheDocument();
    expect(panel.getByText('03/01/2026')).toBeInTheDocument();
    // The line is marked as the one that is open.
    expect(screen.getByRole('button', { name: 'Compote' })).toHaveAttribute(
      'aria-current',
      'true',
    );
  });

  it('counts the stock, through the API, and shows what the server holds', async () => {
    const fetch = stubFetch({
      [PRODUCTS_URL]: [MUESLI],
      [`PUT /api/v1/inventory/${MUESLI.barcode}/stock`]: {
        barcode: MUESLI.barcode,
        stock: {
          quantity: '250.00',
          unit: 'g',
          counted_at: '2026-10-31T09:00:00Z',
        },
      },
    });
    renderList();
    await screen.findByRole('button', { name: 'Muesli' });
    click('Muesli');

    const field = within(sheet()).getByRole('spinbutton', {
      name: /^Stock – Muesli/,
    });
    fireEvent.change(field, { target: { value: '250' } });
    fireEvent.blur(field);

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        `/api/v1/inventory/${MUESLI.barcode}/stock`,
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({ quantity: 250, unit: 'g' }),
        }),
      ),
    );
    await waitFor(() => expect(field).toHaveValue(250));
    // The line says it too, and the sheet says when it was counted.
    expect(within(rowOf('Muesli')).getByText('250 g')).toBeInTheDocument();
    expect(screen.getByText('Compté le 31/10/2026')).toBeInTheDocument();
  });

  it('counts pots through the API in servings', async () => {
    const fetch = stubFetch({
      [PRODUCTS_URL]: [COMPOTE],
      [`PUT /api/v1/inventory/${COMPOTE.barcode}/stock`]: {
        barcode: COMPOTE.barcode,
        stock: { quantity: '5.00', unit: 'serving', counted_at: null },
      },
    });
    renderList();
    await screen.findByRole('button', { name: 'Compote' });
    click('Compote');

    fireEvent.click(
      within(sheet()).getByRole('button', { name: 'Un de plus : pot' }),
    );

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        `/api/v1/inventory/${COMPOTE.barcode}/stock`,
        expect.objectContaining({
          body: JSON.stringify({ quantity: 5, unit: 'serving' }),
        }),
      ),
    );
    expect(await within(rowOf('Compote')).findByText('5 pots')).toBeVisible();
  });

  it('draws the barcode, and writes a code that cannot scan', async () => {
    stubFetch({
      [PRODUCTS_URL]: [RICE, { ...MUESLI, barcode: '1234567890123' }],
    });
    renderList();
    await screen.findByRole('button', { name: 'Rice' });

    click('Rice');
    expect(
      within(sheet()).getByRole('img', { name: 'Code barre 4006381333931' }),
    ).toBeInTheDocument();

    click('Muesli');
    // Not an EAN-13 (its check digit is wrong): text, not bars.
    expect(
      within(sheet()).queryByRole('img', { name: /1234567890123/ }),
    ).toBeNull();
    expect(within(sheet()).getByText('1234567890123')).toBeInTheDocument();
  });

  it('opens the whole sheet of the product, which is its page', async () => {
    stubFetch({ [PRODUCTS_URL]: [RICE] });
    renderList();
    await screen.findByRole('button', { name: 'Rice' });
    click('Rice');

    expect(
      within(sheet()).getByRole('link', { name: /Ouvrir la fiche complète/ }),
    ).toHaveAttribute('href', '/products/4006381333931/edit/');
  });

  it('is kept in the address, so that a refresh comes back to it', async () => {
    stubFetch({ [PRODUCTS_URL]: [RICE] });
    const { unmount } = renderList();
    await screen.findByRole('button', { name: 'Rice' });

    click('Rice');
    expect(window.location.search).toBe('?product=4006381333931');

    unmount();
    stubFetch({ [PRODUCTS_URL]: [RICE] });
    renderList();
    await screen.findByRole('button', { name: 'Rice' });
    expect(
      within(sheet()).getByRole('heading', { name: 'Rice' }),
    ).toBeInTheDocument();
  });

  it('closes with Escape, or with the way back on a phone', async () => {
    stubFetch({ [PRODUCTS_URL]: [RICE] });
    renderList();
    await screen.findByRole('button', { name: 'Rice' });

    click('Rice');
    fireEvent.keyDown(sheet(), { key: 'Escape' });
    expect(screen.queryByRole('complementary')).toBeNull();
    expect(window.location.search).toBe('');

    click('Rice');
    fireEvent.click(
      within(sheet()).getByRole('button', { name: 'Inventaire' }),
    );
    expect(screen.queryByRole('complementary')).toBeNull();
  });

  it('forgets the product of an address that the list does not show', async () => {
    window.history.replaceState(null, '', '/?product=0000000000000');
    stubFetch({ [PRODUCTS_URL]: [RICE] });
    renderList();
    await screen.findByRole('button', { name: 'Rice' });

    expect(screen.queryByRole('complementary')).toBeNull();
    await waitFor(() => expect(window.location.search).toBe(''));
  });

  it('takes the product out of the inventory, and closes', async () => {
    const fetch = stubFetch({
      [PRODUCTS_URL]: [RICE],
      [`DELETE /api/v1/inventory/${RICE.barcode}`]: {},
    });
    renderList();
    await screen.findByRole('button', { name: 'Rice' });
    click('Rice');

    fireEvent.click(
      within(sheet()).getByRole('button', {
        name: 'Retirer de mon inventaire',
      }),
    );

    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Rice' })).toBeNull(),
    );
    expect(screen.queryByRole('complementary')).toBeNull();
    expect(fetch).toHaveBeenLastCalledWith(
      '/api/v1/inventory/4006381333931',
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('says so when the inventory cannot be changed, and stays', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    stubFetch({
      [PRODUCTS_URL]: [RICE],
      [`DELETE /api/v1/inventory/${RICE.barcode}`]: new Error('403'),
    });
    renderList();
    await screen.findByRole('button', { name: 'Rice' });
    click('Rice');

    fireEvent.click(
      within(sheet()).getByRole('button', {
        name: 'Retirer de mon inventaire',
      }),
    );

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "Votre inventaire n'a pas pu être modifié.",
    );
    expect(screen.getByRole('button', { name: 'Rice' })).toBeInTheDocument();
    expect(sheet()).toBeInTheDocument();
  });

  it('interpolates the product name into the delete confirmation', async () => {
    stubFetch({ [PRODUCTS_URL]: [RICE] });
    // Returning false keeps jsdom from attempting a real form submission.
    const confirm = vi.fn().mockReturnValue(false);
    vi.stubGlobal('confirm', confirm);
    renderList();
    await screen.findByRole('button', { name: 'Rice' });
    click('Rice');

    within(sheet())
      .getByRole('button', { name: /Supprimer du catalogue/ })
      .click();

    expect(confirm).toHaveBeenCalledWith('Supprimer « Rice » ?');
  });

  it('puts the server-supplied CSRF token on the delete form', async () => {
    // CSRF_COOKIE_HTTPONLY hides the token from document.cookie, so reading it
    // client-side yields an empty string and every delete POST 403s.
    stubFetch({ [PRODUCTS_URL]: [RICE] });
    renderList();
    await screen.findByRole('button', { name: 'Rice' });
    click('Rice');

    const field = sheet().querySelector('[name="csrfmiddlewaretoken"]');
    expect(field).not.toBeNull();
    expect(field.value).toBe(CSRF_TOKEN);
    expect(field.form).toHaveAttribute(
      'action',
      '/products/4006381333931/delete/',
    );
  });

  it('offers no deletion to users who may not delete, and says what it does to those who may', async () => {
    stubFetch({ [PRODUCTS_URL]: [RICE] });
    const { unmount } = renderList({ canDelete: false });
    await screen.findByRole('button', { name: 'Rice' });
    click('Rice');

    // Deleting is reserved to staff server-side; the sheet must not offer a
    // button that can only end in a 403.
    expect(
      screen.queryByRole('button', { name: /Supprimer du catalogue/ }),
    ).toBeNull();
    expect(screen.queryByText('Administrateur')).toBeNull();

    unmount();
    stubFetch({ [PRODUCTS_URL]: [RICE] });
    renderList({ canDelete: true });
    await screen.findByRole('button', { name: 'Rice' });

    expect(screen.getByText('Administrateur')).toBeInTheDocument();
    expect(
      screen.getByText('Le produit disparaît pour tous les utilisateurs.'),
    ).toBeInTheDocument();
  });
});

describe('ProductListApp, the inventory and the catalogue', () => {
  it("shows the user's inventory first, and every product on request", async () => {
    stubFetch({ [PRODUCTS_URL]: [RICE, OATS] });
    renderList();

    await screen.findByRole('button', { name: 'Rice' });
    expect(screen.queryByRole('button', { name: 'Oats' })).toBeNull();
    expect(
      screen.getByRole('button', { name: 'Mon inventaire' }),
    ).toHaveAttribute('aria-pressed', 'true');

    click('Tous les produits');

    expect(screen.getByRole('button', { name: 'Oats' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rice' })).toBeInTheDocument();
  });

  it('keeps the view chosen from one visit to the next', async () => {
    stubFetch({ [PRODUCTS_URL]: [RICE, OATS] });
    const { unmount } = renderList();
    await screen.findByRole('button', { name: 'Rice' });
    click('Tous les produits');
    unmount();

    stubFetch({ [PRODUCTS_URL]: [RICE, OATS] });
    renderList();

    expect(
      await screen.findByRole('button', { name: 'Tous les produits' }),
    ).toHaveAttribute('aria-pressed', 'true');
    expect(await screen.findByRole('button', { name: 'Oats' })).toBeVisible();
  });

  it('says in the catalogue what is in the inventory, as a state and not a button', async () => {
    stubFetch({ [PRODUCTS_URL]: [RICE, OATS] });
    renderList();
    await screen.findByRole('button', { name: 'Rice' });

    click('Tous les produits');

    expect(
      within(rowOf('Rice')).getByText('Dans mon inventaire'),
    ).toBeInTheDocument();
    expect(
      within(rowOf('Rice')).queryByRole('button', { name: /inventaire/ }),
    ).toBeNull();
    expect(
      within(rowOf('Oats')).getByRole('button', {
        name: 'Ajouter à mon inventaire',
      }),
    ).toBeInTheDocument();
  });

  it('puts a product in the inventory with the CSRF token', async () => {
    const fetch = stubFetch({
      [PRODUCTS_URL]: [RICE, OATS],
      [`PUT /api/v1/inventory/${OATS.barcode}`]: {},
    });
    renderList();
    await screen.findByRole('button', { name: 'Rice' });
    click('Tous les produits');

    fireEvent.click(
      within(rowOf('Oats')).getByRole('button', {
        name: 'Ajouter à mon inventaire',
      }),
    );

    expect(
      await within(rowOf('Oats')).findByText('Dans mon inventaire'),
    ).toBeVisible();
    expect(fetch).toHaveBeenLastCalledWith('/api/v1/inventory/3229820794556', {
      method: 'PUT',
      headers: { Accept: 'application/json', 'X-CSRFToken': CSRF_TOKEN },
    });
    // In the inventory, and not counted yet.
    click('Mon inventaire');
    expect(
      within(rowOf('Oats')).getByText('Stock non compté'),
    ).toBeInTheDocument();
  });

  it('puts a product in the inventory from its sheet, which then counts it', async () => {
    stubFetch({
      [PRODUCTS_URL]: [RICE, OATS],
      [`PUT /api/v1/inventory/${OATS.barcode}`]: {},
    });
    renderList();
    await screen.findByRole('button', { name: 'Rice' });
    click('Tous les produits');
    click('Oats');
    // Not in the inventory: nothing to count yet.
    expect(within(sheet()).queryByRole('spinbutton')).toBeNull();

    fireEvent.click(
      within(sheet()).getByRole('button', { name: 'Ajouter à mon inventaire' }),
    );

    expect(await within(sheet()).findByRole('spinbutton')).toBeVisible();
    expect(
      within(sheet()).getByRole('button', {
        name: 'Retirer de mon inventaire',
      }),
    ).toBeInTheDocument();
  });

  it('says how to fill an empty inventory', async () => {
    stubFetch({ [PRODUCTS_URL]: [OATS] });
    renderList();

    expect(
      await screen.findByText(
        'Votre inventaire est vide. Affichez tous les produits pour en ajouter.',
      ),
    ).toBeInTheDocument();
  });
});

describe('ProductListApp, finding a product', () => {
  const products = [COMPOTE, { ...RICE, name: 'Pâtes girandole' }, USED_UP];

  const chip = (name) => screen.getByRole('button', { name });

  it('says how many products each stock filter keeps', async () => {
    stubFetch({ [PRODUCTS_URL]: products });
    renderList();
    await screen.findByRole('button', { name: 'Compote' });

    expect(chip('Tous 3')).toHaveAttribute('aria-pressed', 'true');
    expect(chip('En stock 1')).toBeInTheDocument();
    expect(chip('Épuisés 1')).toBeInTheDocument();
    expect(chip('Non comptés 1')).toBeInTheDocument();
  });

  it('keeps the products of the filter chosen, which is kept too', async () => {
    stubFetch({ [PRODUCTS_URL]: products });
    const { unmount } = renderList();
    await screen.findByRole('button', { name: 'Compote' });

    fireEvent.click(chip('Épuisés 1'));
    expect(names()).toEqual(['Muesli']);
    expect(chip('Épuisés 1')).toHaveAttribute('aria-pressed', 'true');
    unmount();

    stubFetch({ [PRODUCTS_URL]: products });
    renderList();
    await screen.findByRole('button', { name: 'Muesli' });
    expect(names()).toEqual(['Muesli']);
  });

  it('keeps the products in stock, and those not counted', async () => {
    stubFetch({ [PRODUCTS_URL]: products });
    renderList();
    await screen.findByRole('button', { name: 'Compote' });

    fireEvent.click(chip('En stock 1'));
    expect(names()).toEqual(['Compote']);

    fireEvent.click(chip('Non comptés 1'));
    expect(names()).toEqual(['Pâtes girandole']);
  });

  it('has no filter among all the products, which are not all counted', async () => {
    stubFetch({ [PRODUCTS_URL]: products });
    renderList();
    await screen.findByRole('button', { name: 'Compote' });
    fireEvent.click(chip('Épuisés 1'));

    click('Tous les produits');

    expect(
      screen.queryByRole('group', { name: 'Filtrer selon le stock' }),
    ).toBeNull();
    // The filter does not narrow what it is not shown for.
    expect(names()).toHaveLength(3);
  });

  it('searches by name, without regard to accents or case', async () => {
    stubFetch({ [PRODUCTS_URL]: products });
    renderList();
    await screen.findByRole('button', { name: 'Compote' });

    fireEvent.change(
      screen.getByRole('searchbox', { name: 'Rechercher un produit' }),
      { target: { value: 'PATES' } },
    );

    expect(names()).toEqual(['Pâtes girandole']);
  });

  it('searches by barcode', async () => {
    stubFetch({ [PRODUCTS_URL]: products });
    renderList();
    await screen.findByRole('button', { name: 'Compote' });

    fireEvent.change(screen.getByRole('searchbox'), {
      target: { value: '3245412' },
    });

    expect(names()).toEqual(['Compote']);
  });

  it('says so when nothing matches', async () => {
    stubFetch({ [PRODUCTS_URL]: products });
    renderList();
    await screen.findByRole('button', { name: 'Compote' });

    fireEvent.change(screen.getByRole('searchbox'), {
      target: { value: 'caviar' },
    });

    expect(
      screen.getByText('Aucun produit ne correspond.'),
    ).toBeInTheDocument();
  });

  it('keeps the sheet open while the search goes on', async () => {
    stubFetch({ [PRODUCTS_URL]: products });
    renderList();
    await screen.findByRole('button', { name: 'Compote' });
    click('Compote');

    fireEvent.change(screen.getByRole('searchbox'), {
      target: { value: 'pates' },
    });

    expect(sheet()).toBeInTheDocument();
  });
});

describe('ProductListApp, the groups', () => {
  it('cuts the products into groups named in the language served', async () => {
    stubFetch({
      [PRODUCTS_URL]: [
        { ...RICE, group_level_1: 'Fish Meat Eggs', group_level_2: 'unknown' },
        { ...OATS, in_inventory: true },
        {
          ...OATS,
          barcode: '3263670115819',
          name: 'Mystery',
          in_inventory: true,
          group_level_1: '',
          group_level_2: '',
        },
      ],
    });
    renderList();
    await screen.findByRole('button', { name: 'Rice' });

    const heads = screen
      .getAllByRole('button', { expanded: true })
      .map((button) => button.textContent);
    // By name, the unclassified last, each with how many products it holds.
    expect(heads).toEqual([
      'Céréales et pommes de terre1',
      'Viandes, poissons et œufs1',
      'Non classé1',
    ]);
    // A subgroup is titled where its group has known ones, and not elsewhere.
    const titles = [...document.querySelectorAll('.inventory-subgroup')].map(
      (title) => title.textContent,
    );
    expect(titles).toEqual(['Céréales du petit-déjeuner']);
  });

  it('titles the subgroups of a group, and puts the unclassified ones last', async () => {
    stubFetch({
      [PRODUCTS_URL]: [
        { ...RICE, group_level_2: 'unknown' },
        { ...OATS, in_inventory: true },
        {
          ...OATS,
          barcode: '3263670115819',
          name: 'Barley',
          in_inventory: true,
          group_level_2: 'Cereals',
        },
      ],
    });
    renderList();
    await screen.findByRole('button', { name: 'Rice' });

    const titles = [...document.querySelectorAll('.inventory-subgroup')].map(
      (title) => title.textContent,
    );
    expect(titles).toEqual([
      'Céréales',
      'Céréales du petit-déjeuner',
      'Non classé',
    ]);
    // Inside a subgroup the products are by name.
    expect(names()).toEqual(['Barley', 'Oats', 'Rice']);
  });

  it('folds a group away and brings it back', async () => {
    stubFetch({ [PRODUCTS_URL]: [RICE, { ...OATS, in_inventory: true }] });
    renderList();
    await screen.findByRole('button', { name: 'Rice' });

    const head = screen.getByRole('button', {
      name: /Céréales et pommes de terre/,
    });
    fireEvent.click(head);

    expect(head).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('button', { name: 'Rice' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Oats' })).toBeNull();

    fireEvent.click(head);

    expect(head).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', { name: 'Rice' })).toBeInTheDocument();
  });
});
