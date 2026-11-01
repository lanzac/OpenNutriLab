import { createRoot } from 'react-dom/client';

import { Barcode } from '../Barcode.jsx';

const WIDTH = 180;

/**
 * The picture of the product's barcode on its page, the one the inventory's sheet
 * shows (a scanner can read it off the screen).
 *
 * @param {{ label: string }} labels Translated server-side (see
 *   product_form_config in opennutrilab/products/views.py).
 */
export function initBarcodeImage(labels) {
  const mount = document.getElementById('barcode-image');
  if (!mount || !mount.dataset.code) return;
  createRoot(mount).render(
    <Barcode code={mount.dataset.code} label={labels.label} width={WIDTH} />,
  );
}
