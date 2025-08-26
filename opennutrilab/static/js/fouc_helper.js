// FOUC helper script
// https://www.fabienlasserre.dev/en/blog/how-to-get-rid-of-the-flash-of-unstyled-content/

// Helper function
let domReady = (cb) => {
  document.readyState === 'interactive' || document.readyState === 'complete'
    ? cb()
    : document.addEventListener('DOMContentLoaded', cb);
};

domReady(() => {
  // Remove FOUC class when DOM is loaded
  document.body.classList.remove('fouc-hidden');
});
