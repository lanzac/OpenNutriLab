import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { COMPOTE, labels, MUESLI } from './fixtures.js';
import { StockEditor } from './StockEditor.jsx';

const field = (name = 'Muesli') =>
  screen.getByRole('spinbutton', { name: new RegExp(`^Stock – ${name}`) });

function renderEditor(product = MUESLI, onCount = vi.fn().mockResolvedValue()) {
  const editor = (shown) => (
    <StockEditor
      product={shown}
      labels={labels}
      languageCode="fr-fr"
      onCount={onCount}
    />
  );
  const view = render(editor(product));
  const again = (next) => view.rerender(editor(next));
  return { onCount, again, ...view };
}

const type = (input, value) => {
  fireEvent.change(input, { target: { value } });
  fireEvent.blur(input);
};

const uncounted = (product) => ({
  ...product,
  stock: { quantity: null, unit: product.stock.unit, counted_at: null },
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('StockEditor', () => {
  it('shows the stock in its unit, and the day it was counted', () => {
    renderEditor();

    expect(field()).toHaveValue(300);
    expect(screen.getByText('g')).toBeInTheDocument();
    expect(screen.getByText('Compté le 10/10/2026')).toBeInTheDocument();
  });

  it('asks for a count where the stock was never counted, and says what that means', () => {
    renderEditor(uncounted(MUESLI));

    expect(field()).toHaveValue(null);
    expect(field()).toHaveAttribute('placeholder', 'Non compté');
    expect(screen.queryByText(/Compté le/)).not.toBeInTheDocument();
    expect(
      screen.getByText(/rien ne limite les repas, et rien n'est retiré/),
    ).toBeInTheDocument();
  });

  it('says what the stock comes to in packages', () => {
    const { again } = renderEditor();
    // 300 g of a package of 375 g.
    expect(screen.getByText('Soit 0,8 paquet.')).toBeInTheDocument();

    again({ ...MUESLI, stock: { ...MUESLI.stock, quantity: '562.50' } });
    expect(screen.getByText('Soit 1,5 paquet.')).toBeInTheDocument();

    again({ ...MUESLI, stock: { ...MUESLI.stock, quantity: '750.00' } });
    expect(screen.getByText('Soit 2 paquets.')).toBeInTheDocument();
  });

  it('says nothing of packages for a product that has none', () => {
    renderEditor({ ...MUESLI, package: null });

    expect(screen.queryByText(/^Soit/)).not.toBeInTheDocument();
  });

  it('keeps the stock as the field is left, with no button to save it', () => {
    const { onCount } = renderEditor();

    type(field(), '250');

    expect(onCount).toHaveBeenCalledWith(MUESLI, 250, 'g');
  });

  it('keeps it on Enter', () => {
    const { onCount } = renderEditor();

    fireEvent.change(field(), { target: { value: '120.5' } });
    field().focus();
    fireEvent.keyDown(field(), { key: 'Enter' });
    // Enter leaves the field, as a person does; jsdom needs the focus to be there.
    fireEvent.blur(field());

    expect(onCount).toHaveBeenCalledWith(MUESLI, 120.5, 'g');
  });

  it('says the stock is not counted when the field is emptied', () => {
    const { onCount } = renderEditor();

    type(field(), '');

    expect(onCount).toHaveBeenCalledWith(MUESLI, null, 'g');
  });

  it('counts nothing as used up, which is not the same as not counted', () => {
    const { onCount } = renderEditor();

    type(field(), '0');

    expect(onCount).toHaveBeenCalledWith(MUESLI, 0, 'g');
  });

  it('keeps nothing when the stock is as it was', () => {
    const { onCount } = renderEditor();

    fireEvent.blur(field());
    type(field(), '300.0');

    expect(onCount).not.toHaveBeenCalled();
    expect(field()).toHaveValue(300);
  });

  it('goes back to the stock kept when the quantity is below nothing', () => {
    const { onCount } = renderEditor();

    type(field(), '-5');

    expect(onCount).not.toHaveBeenCalled();
    expect(field()).toHaveValue(300);
  });

  it('says so, and goes back to the stock kept, when it could not be saved', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const { onCount } = renderEditor(
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

  it('follows the stock when the server holds another, as the meals eaten take from it', () => {
    const { again } = renderEditor();

    again({ ...MUESLI, stock: { ...MUESLI.stock, quantity: '240.00' } });

    expect(field()).toHaveValue(240);
  });
});

describe('StockEditor, a package', () => {
  const addPackage = () => screen.getByRole('button', { name: /Un paquet · / });

  it('is added to the stock with a button that says what it holds', () => {
    const { onCount } = renderEditor();

    fireEvent.click(screen.getByRole('button', { name: 'Un paquet · 375 g' }));

    expect(onCount).toHaveBeenCalledWith(MUESLI, 675, 'g');
  });

  it('is added to what is typed, not yet kept', () => {
    const { onCount } = renderEditor();

    fireEvent.change(field(), { target: { value: '100' } });
    fireEvent.click(addPackage());

    expect(onCount).toHaveBeenCalledWith(MUESLI, 475, 'g');
  });

  it('starts the count at a package where there was none', () => {
    const none = uncounted(MUESLI);
    const { onCount } = renderEditor(none);

    fireEvent.click(addPackage());

    expect(onCount).toHaveBeenCalledWith(none, 375, 'g');
  });

  it('is added without float dust', () => {
    const { onCount } = renderEditor({
      ...MUESLI,
      package: { quantity: '0.1', unit: 'g' },
      stock: { ...MUESLI.stock, quantity: '0.20' },
    });

    fireEvent.click(addPackage());

    expect(onCount.mock.calls[0][1]).toBe(0.3);
  });

  it('has no button where the product has no package, or none in the unit counted', () => {
    const { again } = renderEditor({ ...MUESLI, package: null });
    expect(screen.queryByRole('button', { name: /Un paquet/ })).toBeNull();

    again({ ...MUESLI, stock: { ...MUESLI.stock, quantity: '2', unit: 'ml' } });
    expect(screen.queryByRole('button', { name: /Un paquet/ })).toBeNull();
  });
});

describe('StockEditor, used up', () => {
  it('says the product is used up with a button', () => {
    const { onCount } = renderEditor();

    fireEvent.click(screen.getByRole('button', { name: 'Marquer épuisé' }));

    expect(onCount).toHaveBeenCalledWith(MUESLI, 0, 'g');
  });

  it('has nothing to say where the stock is at nothing already', () => {
    renderEditor({ ...MUESLI, stock: { ...MUESLI.stock, quantity: '0.00' } });

    expect(field()).toHaveValue(0);
    expect(
      screen.getByRole('button', { name: 'Marquer épuisé' }),
    ).toBeDisabled();
  });

  it('can be said where nothing was counted', () => {
    const none = uncounted(MUESLI);
    const { onCount } = renderEditor(none);

    fireEvent.click(screen.getByRole('button', { name: 'Marquer épuisé' }));

    expect(onCount).toHaveBeenCalledWith(none, 0, 'g');
  });
});

describe('StockEditor, a product counted by pot', () => {
  const unitButton = (name) => screen.getByRole('button', { name });

  it('shows the pots, what they weigh and how many packages they make', () => {
    renderEditor(COMPOTE);

    expect(field('Compote')).toHaveValue(4);
    expect(screen.getByText('Soit 400 g, 1 paquet.')).toBeInTheDocument();
    expect(unitButton('pots')).toHaveAttribute('aria-pressed', 'true');
    expect(unitButton('g')).toHaveAttribute('aria-pressed', 'false');
  });

  it('goes up and down by one pot, one save at a time', async () => {
    const { onCount } = renderEditor(COMPOTE);

    fireEvent.click(unitButton('Un de plus : pot'));
    // While it is kept, the buttons wait: two taps would both start from the stock held.
    expect(unitButton('Un de moins : pot')).toBeDisabled();
    await waitFor(() =>
      expect(unitButton('Un de moins : pot')).not.toBeDisabled(),
    );
    fireEvent.click(unitButton('Un de moins : pot'));

    expect(onCount).toHaveBeenNthCalledWith(1, COMPOTE, 5, 'serving');
    expect(onCount).toHaveBeenNthCalledWith(2, COMPOTE, 3, 'serving');
  });

  it('goes from what is typed', () => {
    const { onCount } = renderEditor(COMPOTE);

    fireEvent.change(field('Compote'), { target: { value: '7' } });
    fireEvent.click(unitButton('Un de plus : pot'));

    expect(onCount).toHaveBeenCalledWith(COMPOTE, 8, 'serving');
  });

  it('cannot go below nothing', () => {
    const { again } = renderEditor({
      ...COMPOTE,
      stock: { ...COMPOTE.stock, quantity: '0.00' },
    });
    expect(unitButton('Un de moins : pot')).toBeDisabled();

    again(uncounted(COMPOTE));
    expect(unitButton('Un de moins : pot')).toBeDisabled();
  });

  it('starts the count at one pot where there was none', () => {
    const none = uncounted(COMPOTE);
    const { onCount } = renderEditor(none);

    fireEvent.click(unitButton('Un de plus : pot'));

    expect(onCount).toHaveBeenCalledWith(none, 1, 'serving');
  });

  it('keeps pots whole', () => {
    const { onCount } = renderEditor(COMPOTE);

    type(field('Compote'), '2.5');

    expect(onCount).not.toHaveBeenCalled();
    expect(field('Compote')).toHaveValue(4);
    expect(field('Compote')).toHaveAttribute('step', '1');
  });

  it('keeps a count of pots with the unit it is in', () => {
    const { onCount } = renderEditor(COMPOTE);

    type(field('Compote'), '3');

    expect(onCount).toHaveBeenCalledWith(COMPOTE, 3, 'serving');
  });

  it('adds a package of pots: 4 more', () => {
    const { onCount } = renderEditor(COMPOTE);

    fireEvent.click(unitButton('Un paquet · 4 pots'));

    expect(onCount).toHaveBeenCalledWith(COMPOTE, 8, 'serving');
  });

  it('turns the count into grams when the unit is changed', () => {
    const { onCount } = renderEditor(COMPOTE);

    fireEvent.click(unitButton('g'));

    expect(onCount).toHaveBeenCalledWith(COMPOTE, 400, 'g');
  });

  it('turns grams into the pots they need, a started pot being a pot', () => {
    const grams = {
      ...COMPOTE,
      stock: { ...COMPOTE.stock, quantity: '450.00', unit: 'g' },
    };
    const { onCount } = renderEditor(grams);

    fireEvent.click(unitButton('pots'));

    expect(onCount).toHaveBeenCalledWith(grams, 5, 'serving');
  });

  it('counts in the unit chosen while nothing is counted', () => {
    const none = uncounted(COMPOTE);
    const { onCount } = renderEditor(none);

    fireEvent.click(unitButton('g'));
    expect(onCount).not.toHaveBeenCalled();
    expect(unitButton('g')).toHaveAttribute('aria-pressed', 'true');
    type(field('Compote'), '250');

    expect(onCount).toHaveBeenCalledWith(none, 250, 'g');
  });

  it('offers no choice of unit for a product that has no serving to count by', () => {
    renderEditor(MUESLI);

    expect(
      screen.queryByRole('group', { name: 'Unité du stock' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Un de plus/ }),
    ).not.toBeInTheDocument();
  });
});
