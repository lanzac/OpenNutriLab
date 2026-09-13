import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ProductListApp } from './ProductListApp.jsx';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ProductListApp', () => {
  it('renders products fetched from the API', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [
          {
            barcode: '1234567890123',
            name: 'Rice',
            created_at: '2026-01-01T00:00:00Z',
          },
        ],
      }),
    );

    render(<ProductListApp />);

    await waitFor(() => expect(screen.getByText('Rice')).toBeInTheDocument());
    expect(
      screen.getByRole('link', { name: /edit/i }),
    ).toHaveAttribute('href', '/products/1234567890123/edit/');
  });

  it('shows an error message when the fetch fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 500 }),
    );

    render(<ProductListApp />);

    await waitFor(() =>
      expect(screen.getByText(/failed to load products/i)).toBeInTheDocument(),
    );
  });
});
