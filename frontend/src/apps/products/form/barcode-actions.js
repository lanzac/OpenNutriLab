// Barcode fetch / reset buttons on the product form. Both reload the page
// with a query parameter that ProductCreateView reads server-side.
// Ported from opennutrilab/static/js/fetch_barcode.js (webpack entry
// 'fetch_barcode') without behaviour changes.

function reloadWith(param, value) {
  const url = new URL(window.location.href);
  url.searchParams.set(param, value);
  window.location.href = url.toString();
}

/**
 * @param {{ enterBarcode: string }} labels Translated server-side (see
 *   product_form_labels in products/views.py).
 */
export function initBarcodeActions(labels) {
  const fetchButton = document.getElementById('fetch-product-data');
  const resetButton = document.getElementById('reset-product-data');
  const barcodeField = document.getElementById('id_barcode');

  if (fetchButton && barcodeField) {
    fetchButton.addEventListener('click', () => {
      const barcode = barcodeField.value.trim();
      if (barcode) {
        reloadWith('barcode', barcode);
      } else {
        alert(labels.enterBarcode);
      }
    });
  }

  if (resetButton) {
    resetButton.addEventListener('click', () => reloadWith('reset', '1'));
  }
}
