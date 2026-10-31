import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { labels as listLabels, OATS, RICE } from './fixtures.js';
import { ProductListApp } from './ProductListApp.jsx';
import { scanLabels } from './scan/labels.js';

// The camera is BarcodeScanner's business: here it is a stand-in that lets a
// test say what it saw.
let detect;
vi.mock('./scan/BarcodeScanner.jsx', () => ({
  BarcodeScanner: ({ onDetect }) => {
    detect = onDetect;
    return <div data-testid="camera" />;
  },
}));

const labels = { ...scanLabels, ...listLabels };

function renderList() {
  const fetchMock = vi.fn().mockImplementation(async (url, options) => ({
    ok: true,
    json: async () => (options?.method ? {} : [RICE, OATS]),
  }));
  vi.stubGlobal('fetch', fetchMock);
  render(
    <ProductListApp
      labels={labels}
      groupNames={{}}
      csrfToken="test-csrf-token"
      languageCode="fr-fr"
      canDelete={false}
      placeholderImage="/static/images/milk-carton.png"
    />,
  );
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('ProductListApp, scanning', () => {
  it('opens the scanner from a button, and closes it', async () => {
    renderList();
    await screen.findByText('Rice');
    expect(screen.queryByTestId('camera')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Scanner un produit/ }));
    expect(screen.getByTestId('camera')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Fermer le scanner' }));
    expect(screen.queryByTestId('camera')).not.toBeInTheDocument();
  });

  it('shows in the list the product it put in the inventory', async () => {
    const fetchMock = renderList();
    await screen.findByText('Rice');
    // The oats are not in the inventory, which is what the list shows.
    expect(screen.queryByText('Oats')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Scanner un produit/ }));
    act(() => detect(OATS.barcode));

    await waitFor(() => expect(screen.getByText('Oats')).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/inventory/${OATS.barcode}`,
      expect.objectContaining({ method: 'PUT' }),
    );
    // In the inventory like the others, and not counted yet: the scan did not break it.
    expect(
      screen
        .getByRole('button', { name: 'Oats' })
        .closest('li')
        .textContent.includes('Stock non compté'),
    ).toBe(true);
  });
});
