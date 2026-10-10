import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { scanLabels as labels } from './labels.js';
import { ProductScanner } from './ProductScanner.jsx';

// The camera is BarcodeScanner's business, tested there: here it is a stand-in
// that lets a test say what it saw.
let detect;
vi.mock('./BarcodeScanner.jsx', () => ({
  BarcodeScanner: ({ onDetect }) => {
    detect = onDetect;
    return <div data-testid="camera" />;
  },
}));

const RICE = '4006381333931';
const OATS = '3229820794556';
const UNKNOWN = '3017620422003';

const PRODUCTS = [
  { barcode: RICE, name: 'Rice', in_inventory: true },
  { barcode: OATS, name: 'Oats', in_inventory: false },
];

const CSRF_TOKEN = 'test-csrf-token';

function renderScanner({ products = PRODUCTS, ...props } = {}) {
  const onAdded = vi.fn();
  const onClose = vi.fn();
  render(
    <ProductScanner
      products={products}
      labels={labels}
      csrfToken={CSRF_TOKEN}
      onAdded={onAdded}
      onClose={onClose}
      {...props}
    />,
  );
  return { onAdded, onClose };
}

let fetchMock;

beforeEach(() => {
  fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
  vi.stubGlobal('fetch', fetchMock);
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('ProductScanner', () => {
  it('puts a product of the catalogue in the inventory', async () => {
    const { onAdded } = renderScanner();

    act(() => detect(OATS, 'camera'));

    expect(
      await screen.findByText('« Oats » a été ajouté à votre inventaire.'),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/inventory/${OATS}`,
      expect.objectContaining({
        method: 'PUT',
        headers: expect.objectContaining({ 'X-CSRFToken': CSRF_TOKEN }),
      }),
    );
    expect(onAdded).toHaveBeenCalledWith(OATS);
  });

  it('says so when the product is in the inventory already, and writes nothing', async () => {
    const { onAdded } = renderScanner();

    act(() => detect(RICE, 'camera'));

    expect(
      await screen.findByText('« Rice » est déjà dans votre inventaire.'),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(onAdded).not.toHaveBeenCalled();
  });

  it('offers to create a product the catalogue does not have', async () => {
    const { onAdded } = renderScanner();

    act(() => detect(UNKNOWN, 'camera'));

    expect(
      await screen.findByText(
        `Le code ${UNKNOWN} n'est pas encore dans le catalogue.`,
      ),
    ).toBeInTheDocument();
    // The create page asks OpenFoodFacts for the rest.
    expect(
      screen.getByRole('link', { name: labels.scanCreate }),
    ).toHaveAttribute('href', `/products/new/?barcode=${UNKNOWN}`);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(onAdded).not.toHaveBeenCalled();
  });

  it('says so when the inventory could not be changed', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 500 });
    const { onAdded } = renderScanner();

    act(() => detect(OATS, 'camera'));

    expect(await screen.findByText(labels.inventoryError)).toBeInTheDocument();
    expect(onAdded).not.toHaveBeenCalled();
  });

  it('acts once on a barcode that stays in view', async () => {
    const { onAdded } = renderScanner();

    act(() => {
      detect(OATS, 'camera');
      detect(OATS, 'camera');
      detect(OATS, 'camera');
    });

    await waitFor(() => expect(onAdded).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
  });

  it('answers a photo of a barcode the camera has just read', () => {
    renderScanner();

    act(() => detect(RICE, 'camera'));
    act(() => detect(RICE, 'picture'));

    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });

  it('acts again on a barcode that left the view for a while', () => {
    const now = vi.spyOn(Date, 'now').mockReturnValue(1_000_000);
    renderScanner();

    act(() => detect(RICE, 'camera'));
    // Out of the picture for five seconds, then back.
    now.mockReturnValue(1_005_000);
    act(() => detect(RICE, 'camera'));

    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });

  it('reads the products as they are now, not as they were when the camera started', async () => {
    const { rerender } = render(
      <ProductScanner
        products={PRODUCTS}
        labels={labels}
        csrfToken={CSRF_TOKEN}
        onAdded={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    // The list has put the oats in the inventory since.
    rerender(
      <ProductScanner
        products={PRODUCTS.map((p) => ({ ...p, in_inventory: true }))}
        labels={labels}
        csrfToken={CSRF_TOKEN}
        onAdded={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    act(() => detect(OATS, 'camera'));

    expect(
      await screen.findByText('« Oats » est déjà dans votre inventaire.'),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('shows the last scans first, and only a few', () => {
    const now = vi.spyOn(Date, 'now');
    renderScanner();

    // One barcode after the other, seven times: the catalogue's rice, which is
    // in the inventory, and one it does not know.
    for (let i = 0; i < 7; i++) {
      now.mockReturnValue(1_000_000 + i * 10_000);
      act(() => detect(i % 2 ? RICE : UNKNOWN, 'camera'));
    }

    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(5);
    // The seventh scan was of the unknown one: it is on top.
    expect(within(items[0]).getByRole('link')).toHaveAttribute(
      'href',
      `/products/new/?barcode=${UNKNOWN}`,
    );
    expect(within(items[1]).queryByRole('link')).not.toBeInTheDocument();
  });

  it('buzzes when it has read a barcode, where the phone can', async () => {
    const vibrate = vi.fn();
    Object.defineProperty(navigator, 'vibrate', {
      value: vibrate,
      configurable: true,
    });
    renderScanner();

    act(() => detect(UNKNOWN, 'camera'));

    expect(vibrate).toHaveBeenCalledOnce();
    delete navigator.vibrate;
  });

  it('closes', () => {
    const { onClose } = renderScanner();

    fireEvent.click(screen.getByRole('button', { name: labels.scanClose }));

    expect(onClose).toHaveBeenCalledOnce();
  });
});
