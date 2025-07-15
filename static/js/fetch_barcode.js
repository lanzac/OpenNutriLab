document.addEventListener("DOMContentLoaded", function () {
    const fetchButton = document.getElementById("fetch-food-data");
    const barcodeField = document.getElementById("id_barcode");

    if (fetchButton && barcodeField) {
        fetchButton.addEventListener("click", () => {
            const barcode = barcodeField.value.trim();
            if (barcode) {
                const url = new URL(window.location.href);
                url.searchParams.set("barcode", barcode);
                url.searchParams.set("refresh_data", "1");
                window.location.href = url.toString();  // 🔁 recharge la page avec ?barcode=...
            } else {
                alert("Veuillez entrer un code-barres.");
            }
        });
    }
});
