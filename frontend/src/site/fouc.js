// FOUC helper script
// https://www.fabienlasserre.dev/en/blog/how-to-get-rid-of-the-flash-of-unstyled-content/
//
// base.html renders <body class="fouc-hidden">, which project.scss hides;
// this reveals it once the DOM is ready.

function domReady(cb) {
  if (
    document.readyState === 'interactive' ||
    document.readyState === 'complete'
  ) {
    cb();
  } else {
    document.addEventListener('DOMContentLoaded', cb);
  }
}

export function initFouc() {
  domReady(() => document.body.classList.remove('fouc-hidden'));
}
