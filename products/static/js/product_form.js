document.addEventListener('DOMContentLoaded', function () {
  // Animation du chevron
  $('#vitaminsCollapse').on('show.bs.collapse', function () {
    $(this)
      .prev()
      .find('.fa-chevron-down')
      .removeClass('fa-chevron-down')
      .addClass('fa-chevron-up');
  });

  $('#vitaminsCollapse').on('hide.bs.collapse', function () {
    $(this)
      .prev()
      .find('.fa-chevron-up')
      .removeClass('fa-chevron-up')
      .addClass('fa-chevron-down');
  });
});
