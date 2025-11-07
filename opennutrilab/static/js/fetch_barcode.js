document.addEventListener('DOMContentLoaded', function () {
  const fetchButton = document.getElementById('fetch-product-data');
  const resetButton = document.getElementById('reset-product-data');
  const barcodeField = document.getElementById('id_barcode');

  if (fetchButton && barcodeField) {
    fetchButton.addEventListener('click', () => {
      const barcode = barcodeField.value.trim();
      if (barcode) {
        const url = new URL(window.location.href);
        url.searchParams.set('barcode', barcode);
        window.location.href = url.toString(); // reload the page with ?barcode=...
      } else {
        alert('Veuillez entrer un code-barres.');
      }
    });
  }

  if (resetButton) {
    resetButton.addEventListener('click', () => {
      const url = new URL(window.location.href);
      url.searchParams.set('reset', '1');
      window.location.href = url.toString();
    });
  }
});
