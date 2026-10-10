import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ProductListApp } from './ProductListApp.jsx';
import { StockCell } from './StockCell.jsx';

const labels = {
  image: 'Photo',
  barcode: 'Code barre',
  uncategorised: 'Non classé',
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
  inventoryEmpty: 'Votre inventaire est vide.',
  inventoryError: "Votre inventaire n'a pas pu être modifié.",
  stock: 'Stock',
  stockUnit: 'Unité du stock',
  stockPackages: 'Nombre de paquets',
  stockServings: 'portions',
  stockNotCounted: 'Non compté',
  stockUsedUp: 'Épuisé',
  stockAddPackage: 'Ajouter un paquet (%(package)s) au stock',
  stockSaveError: "Le stock n'a pas pu être enregistré.",
  packageOfServings: '%(count)s %(noun)s de %(serving)s',
};

// A muesli in grams: its serving has no name that is a thing.
const MUESLI = {
  barcode: '3229820794556',
  name: 'Muesli',
  image: null,
  group_level_1: 'Cereals and potatoes',
  group_level_2: 'Breakfast cereals',
  package: { quantity: '375.00', unit: 'g' },
  serving: { quantity: '30.00', unit: 'g', name: '' },
  count_noun: null,
  created_at: '2026-01-01T00:00:00Z',
  in_inventory: true,
  stock: { quantity: '300.00', unit: 'g' },
};

// A compote in pots of 100 g: counted by pot, which are whole.
const COMPOTE = {
  ...MUESLI,
  barcode: '3245412890987',
  name: 'Compote',
  package: { quantity: '400.00', unit: 'g' },
  serving: { quantity: '100.00', unit: 'g', name: '1 pot' },
  count_noun: 'pot',
  stock: { quantity: '4.00', unit: 'serving' },
};

const field = (name = 'Muesli') =>
  screen.getByRole('spinbutton', { name: new RegExp(`^Stock – ${name}`) });
const packs = (name = 'Muesli') =>
  screen.getByRole('spinbutton', {
    name: new RegExp(`^Nombre de paquets – ${name}`),
  });

function renderCell(product = MUESLI, onCount = vi.fn().mockResolvedValue()) {
  const view = render(
    <table>
      <tbody>
        <tr>
          <StockCell
            product={product}
            labels={labels}
            languageCode="fr-fr"
            onCount={onCount}
          />
        </tr>
      </tbody>
    </table>,
  );
  const again = (next) =>
    view.rerender(
      <table>
        <tbody>
          <tr>
            <StockCell
              product={next}
              labels={labels}
              languageCode="fr-fr"
              onCount={onCount}
            />
          </tr>
        </tbody>
      </table>,
    );
  return { onCount, again, ...view };
}

const type = (input, value) => {
  fireEvent.change(input, { target: { value } });
  fireEvent.blur(input);
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('StockCell', () => {
  it('has nothing for a product that is not in the inventory', () => {
    renderCell({ ...MUESLI, in_inventory: false, stock: null });

    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument();
  });

  it('shows the stock in its unit', () => {
    renderCell();

    expect(field()).toHaveValue(300);
    expect(screen.getByText('g')).toBeInTheDocument();
  });

  it('asks for a count where the stock was never counted', () => {
    renderCell({ ...MUESLI, stock: { quantity: null, unit: 'g' } });

    expect(field()).toHaveValue(null);
    expect(field()).toHaveAttribute('placeholder', 'Non compté');
  });

  it('keeps the stock as the field is left, with no button to save it', () => {
    const { onCount } = renderCell();

    type(field(), '250');

    expect(onCount).toHaveBeenCalledWith(MUESLI, 250, 'g');
  });

  it('keeps it on Enter', () => {
    const { onCount } = renderCell();

    fireEvent.change(field(), { target: { value: '120.5' } });
    field().focus();
    fireEvent.keyDown(field(), { key: 'Enter' });
    // Enter leaves the field, as a person does; jsdom needs the focus to be there.
    fireEvent.blur(field());

    expect(onCount).toHaveBeenCalledWith(MUESLI, 120.5, 'g');
  });

  it('says the stock is not counted when the field is emptied', () => {
    const { onCount } = renderCell();

    type(field(), '');

    expect(onCount).toHaveBeenCalledWith(MUESLI, null, 'g');
  });

  it('counts nothing as used up, which is not the same as not counted', () => {
    const { onCount } = renderCell();

    type(field(), '0');

    expect(onCount).toHaveBeenCalledWith(MUESLI, 0, 'g');
  });

  it('keeps nothing when the stock is as it was', () => {
    const { onCount } = renderCell();

    fireEvent.blur(field());
    type(field(), '300.0');

    expect(onCount).not.toHaveBeenCalled();
    expect(field()).toHaveValue(300);
  });

  it('goes back to the stock kept when the quantity is below nothing', () => {
    const { onCount } = renderCell();

    type(field(), '-5');

    expect(onCount).not.toHaveBeenCalled();
    expect(field()).toHaveValue(300);
  });

  it('says so, and goes back to the stock kept, when it could not be saved', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const { onCount } = renderCell(
      MUESLI,
      vi.fn().mockRejectedValue(new Error('HTTP 500')),
    );

    type(field(), '250');

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "Le stock n'a pas pu être enregistré.",
    );
    expect(onCount).toHaveBeenCalledOnce();
    expect(field()).toHaveValue(300);
  });

  it('adds a package to the stock', () => {
    const { onCount } = renderCell();

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Ajouter un paquet (375 g) au stock – Muesli',
      }),
    );

    expect(onCount).toHaveBeenCalledWith(MUESLI, 675, 'g');
  });

  it('starts the count at a package where there was none', () => {
    const { onCount } = renderCell({
      ...MUESLI,
      stock: { quantity: null, unit: 'g' },
    });

    fireEvent.click(screen.getByRole('button', { name: /Ajouter un paquet/ }));

    expect(onCount).toHaveBeenCalledWith(
      expect.objectContaining({ barcode: MUESLI.barcode }),
      375,
      'g',
    );
  });

  it('adds packages without float dust', () => {
    const { onCount } = renderCell({
      ...MUESLI,
      package: { quantity: '0.1', unit: 'g' },
      stock: { quantity: '0.20', unit: 'g' },
    });

    fireEvent.click(screen.getByRole('button', { name: /Ajouter un paquet/ }));

    expect(onCount.mock.calls[0][1]).toBe(0.3);
  });

  it('has no package to add where the product has none, or in another unit', () => {
    const { again } = renderCell({ ...MUESLI, package: null });
    expect(
      screen.queryByRole('button', { name: /Ajouter un paquet/ }),
    ).not.toBeInTheDocument();

    again({ ...MUESLI, stock: { quantity: '2', unit: 'ml' } });
    expect(
      screen.queryByRole('button', { name: /Ajouter un paquet/ }),
    ).not.toBeInTheDocument();
  });

  it('says a stock at nothing is used up', () => {
    renderCell({ ...MUESLI, stock: { quantity: '0.00', unit: 'g' } });

    expect(screen.getByText('Épuisé')).toBeInTheDocument();
  });

  it('does not say a stock not counted is used up', () => {
    renderCell({ ...MUESLI, stock: { quantity: null, unit: 'g' } });

    expect(screen.queryByText('Épuisé')).not.toBeInTheDocument();
  });

  it('follows the stock when the server holds another, as the meals eaten take from it', () => {
    const { again } = renderCell();

    again({ ...MUESLI, stock: { quantity: '240.00', unit: 'g' } });

    expect(field()).toHaveValue(240);
  });
});

describe('StockCell, the number of packages', () => {
  it('shows how many packages the stock is, next to what one holds', () => {
    renderCell({ ...MUESLI, stock: { quantity: '750.00', unit: 'g' } });

    expect(packs()).toHaveValue(2);
    expect(screen.getByText(/× 375 g =/)).toBeInTheDocument();
  });

  it('shows a part of a package as a decimal', () => {
    renderCell({ ...MUESLI, stock: { quantity: '562.50', unit: 'g' } });

    expect(packs()).toHaveValue(1.5);
  });

  it('counts the stock from the number of packages: 2 boxes are 2 packages', () => {
    const sardines = {
      ...MUESLI,
      name: 'Sardines',
      package: { quantity: '135.00', unit: 'g' },
      stock: { quantity: null, unit: 'g' },
    };
    const { onCount } = renderCell(sardines);

    type(packs('Sardines'), '2');

    expect(onCount).toHaveBeenCalledWith(sardines, 270, 'g');
  });

  it('follows the stock into the packages when it is typed', () => {
    const { again } = renderCell();

    again({ ...MUESLI, stock: { quantity: '1125.00', unit: 'g' } });

    expect(packs()).toHaveValue(3);
  });

  it('keeps nothing when the number of packages is as it was', () => {
    const { onCount } = renderCell({
      ...MUESLI,
      stock: { quantity: '750.00', unit: 'g' },
    });

    type(packs(), '2.0');

    expect(onCount).not.toHaveBeenCalled();
    expect(packs()).toHaveValue(2);
  });

  it('goes back when the number of packages is emptied or below nothing', () => {
    const { onCount } = renderCell({
      ...MUESLI,
      stock: { quantity: '750.00', unit: 'g' },
    });

    type(packs(), '');
    type(packs(), '-1');

    expect(onCount).not.toHaveBeenCalled();
    expect(packs()).toHaveValue(2);
  });

  it('is not there for a product with no package, or in other units than its serving', () => {
    renderCell({ ...MUESLI, package: null });

    expect(
      screen.queryByRole('spinbutton', { name: /Nombre de paquets/ }),
    ).not.toBeInTheDocument();
  });
});

describe('StockCell, a product counted by pot', () => {
  it('shows the pots, and what a package holds in pots', () => {
    renderCell(COMPOTE);

    expect(field('Compote')).toHaveValue(4);
    expect(packs('Compote')).toHaveValue(1);
    expect(screen.getByText(/× 4 pots =/)).toBeInTheDocument();
    expect(
      screen.getByRole('combobox', { name: /Unité du stock/ }),
    ).toHaveValue('serving');
  });

  it('keeps pots whole', () => {
    const { onCount } = renderCell(COMPOTE);

    type(field('Compote'), '2.5');

    expect(onCount).not.toHaveBeenCalled();
    expect(field('Compote')).toHaveValue(4);
    expect(field('Compote')).toHaveAttribute('step', '1');
  });

  it('keeps a count of pots with the unit it is in', () => {
    const { onCount } = renderCell(COMPOTE);

    type(field('Compote'), '3');

    expect(onCount).toHaveBeenCalledWith(COMPOTE, 3, 'serving');
  });

  it('adds a package of pots: 4 more', () => {
    const { onCount } = renderCell(COMPOTE);

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Ajouter un paquet (4 pots) au stock – Compote',
      }),
    );

    expect(onCount).toHaveBeenCalledWith(COMPOTE, 8, 'serving');
  });

  it('counts 3 packages of pots as 12 pots', () => {
    const { onCount } = renderCell(COMPOTE);

    type(packs('Compote'), '3');

    expect(onCount).toHaveBeenCalledWith(COMPOTE, 12, 'serving');
  });

  it('rounds a part of a package up to the pot that is started', () => {
    const { onCount } = renderCell(COMPOTE);

    type(packs('Compote'), '1.3');

    // 5.2 pots: a sixth is started.
    expect(onCount).toHaveBeenCalledWith(COMPOTE, 6, 'serving');
  });

  it('turns the count into grams when the unit is changed', () => {
    const { onCount } = renderCell(COMPOTE);

    fireEvent.change(screen.getByRole('combobox', { name: /Unité du stock/ }), {
      target: { value: 'g' },
    });

    expect(onCount).toHaveBeenCalledWith(COMPOTE, 400, 'g');
  });

  it('turns grams into the pots they need, a started pot being a pot', () => {
    const grams = { ...COMPOTE, stock: { quantity: '450.00', unit: 'g' } };
    const { onCount } = renderCell(grams);

    fireEvent.change(screen.getByRole('combobox', { name: /Unité du stock/ }), {
      target: { value: 'serving' },
    });

    expect(onCount).toHaveBeenCalledWith(grams, 5, 'serving');
  });

  it('counts in the unit chosen while nothing is counted', () => {
    const uncounted = {
      ...COMPOTE,
      stock: { quantity: null, unit: 'serving' },
    };
    const { onCount } = renderCell(uncounted);

    fireEvent.change(screen.getByRole('combobox', { name: /Unité du stock/ }), {
      target: { value: 'g' },
    });
    expect(onCount).not.toHaveBeenCalled();
    type(field('Compote'), '250');

    expect(onCount).toHaveBeenCalledWith(uncounted, 250, 'g');
  });

  it('offers no choice of unit for a product that has no serving to count by', () => {
    renderCell(MUESLI);

    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });
});

describe('ProductListApp stock column', () => {
  const OATS = {
    ...MUESLI,
    barcode: '4006381333931',
    name: 'Oats',
    package: null,
    in_inventory: false,
    stock: null,
  };

  function stubFetch(answers) {
    const fetch = vi.fn((url, init = {}) => {
      const key = `${init.method ?? 'GET'} ${url}`;
      if (!(key in answers)) throw new Error(`unexpected ${key}`);
      return Promise.resolve({ ok: true, json: async () => answers[key] });
    });
    vi.stubGlobal('fetch', fetch);
    return fetch;
  }

  const renderList = () =>
    render(
      <ProductListApp
        labels={labels}
        groupNames={{}}
        csrfToken="csrf"
        languageCode="fr-fr"
        canDelete={false}
        placeholderImage="/p.png"
      />,
    );

  it('puts a column for it in the table', async () => {
    stubFetch({ 'GET /api/v1/products/': [MUESLI, OATS] });
    renderList();

    expect(
      await screen.findByRole('columnheader', { name: 'Stock' }),
    ).toBeInTheDocument();
  });

  it('counts the stock through the API and shows what the server holds', async () => {
    const fetch = stubFetch({
      'GET /api/v1/products/': [MUESLI, OATS],
      [`PUT /api/v1/inventory/${MUESLI.barcode}/stock`]: {
        barcode: MUESLI.barcode,
        stock: { quantity: '250.00', unit: 'g' },
      },
    });
    renderList();
    await screen.findByText('Muesli');

    type(field(), '250');

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        `/api/v1/inventory/${MUESLI.barcode}/stock`,
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({ quantity: 250, unit: 'g' }),
          headers: expect.objectContaining({ 'X-CSRFToken': 'csrf' }),
        }),
      ),
    );
    await waitFor(() => expect(field()).toHaveValue(250));
  });

  it('counts pots through the API in servings', async () => {
    const fetch = stubFetch({
      'GET /api/v1/products/': [COMPOTE],
      [`PUT /api/v1/inventory/${COMPOTE.barcode}/stock`]: {
        barcode: COMPOTE.barcode,
        stock: { quantity: '3.00', unit: 'serving' },
      },
    });
    renderList();
    await screen.findByText('Compote');

    type(field('Compote'), '3');

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        `/api/v1/inventory/${COMPOTE.barcode}/stock`,
        expect.objectContaining({
          body: JSON.stringify({ quantity: 3, unit: 'serving' }),
        }),
      ),
    );
  });

  it('writes the total of a package of pots as pots', async () => {
    stubFetch({ 'GET /api/v1/products/': [COMPOTE] });
    renderList();

    expect(await screen.findByText('4 pots de 100 g')).toBeInTheDocument();
  });

  it('keeps the total of a product counted in grams as grams', async () => {
    stubFetch({ 'GET /api/v1/products/': [MUESLI] });
    renderList();

    expect(await screen.findByText('375 g')).toBeInTheDocument();
  });

  it('has no field for a product that is not in the inventory', async () => {
    stubFetch({ 'GET /api/v1/products/': [MUESLI, OATS] });
    renderList();
    await screen.findByText('Muesli');

    fireEvent.click(screen.getByRole('button', { name: 'Tous les produits' }));

    expect(await screen.findByText('Oats')).toBeInTheDocument();
    // The stock and the number of packages, of the one product that is counted.
    expect(screen.getAllByRole('spinbutton')).toHaveLength(2);
  });
});
