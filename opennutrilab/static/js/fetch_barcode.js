document.addEventListener('DOMContentLoaded', function () {
  const fetchButton = document.getElementById('fetch-food-data');
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
});
