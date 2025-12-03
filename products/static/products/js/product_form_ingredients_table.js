// Script called in opennutrilab/templates/products/product_form.html
window.addEventListener('DOMContentLoaded', () => {
  const loader = document.getElementById('ingredients_graph_loader');
  const plotInputs = document.querySelectorAll('#product-form .plot-input');
  const tableDiv = document.getElementById('ingredients_table');

  if (tableDiv) {
    const ingredientsData = JSON.parse(
      document.getElementById('ingredients-data').textContent,
    );

    var table = new Tabulator('#ingredients_table', {
      height: '311px',
      data: ingredientsData,
      dataTree: true,
      dataTreeCollapseElement: "<i class='fas fa-minus-square'></i>", //fontawesome toggle icon
      dataTreeExpandElement: "<i class='fas fa-plus-square'></i>", //fontawesome toggle icon
      dataTreeStartExpanded: false,
      columns: [
        { title: 'Name', field: 'name', responsive: 0 }, //never hide this column
        {
          title: 'Percentage',
          field: 'percentage',
          responsive: 2,
          formatter: function (cell) {
            let value = cell.getValue();
            return value !== null && value !== undefined
              ? Number(value).toFixed(2) + ' %'
              : '';
          },
        },
        {
          title: 'Recognized',
          field: 'has_reference',
          hozAlign: 'center',
          formatter: 'tickCross',
        },
      ],
      dataTreeChildField: 'ingredients',
    });

    if (loader) {
      loader.style.display = 'none';
    }
  }
});
