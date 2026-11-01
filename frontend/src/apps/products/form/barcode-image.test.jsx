import { act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { initBarcodeImage } from './barcode-image.jsx';

const LABELS = { label: 'Code barre' };

beforeEach(() => {
  document.body.innerHTML = '';
});

afterEach(() => {
  document.body.innerHTML = '';
});

function page(code) {
  document.body.innerHTML = `<div id="barcode-image" data-code="${code}"></div>`;
}

describe('initBarcodeImage', () => {
  it('draws the barcode of the product, named for a screen reader', async () => {
    page('3229820794556');

    await act(async () => initBarcodeImage(LABELS));

    const picture = document.querySelector('#barcode-image svg');
    expect(picture).not.toBeNull();
    expect(picture.getAttribute('aria-label')).toBe('Code barre 3229820794556');
    expect(picture.getAttribute('width')).toBe('180');
  });

  it('writes a code a scanner could not read, and does not draw it', async () => {
    page('12345');

    await act(async () => initBarcodeImage(LABELS));

    expect(document.querySelector('#barcode-image svg')).toBeNull();
    expect(document.getElementById('barcode-image')).toHaveTextContent('12345');
  });

  it('does nothing on a page that has no place for it', async () => {
    await act(async () => initBarcodeImage(LABELS));

    expect(document.body.innerHTML).toBe('');
  });
});
