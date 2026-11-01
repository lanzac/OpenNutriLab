// The groups of the nutrients on the product form (see
// opennutrilab/templates/crispy_bootstrap_extend/foldable-group.html): each says how
// many of its figures hold a value, and a person's choice to leave it open or closed
// is kept from one visit to the next. Bootstrap folds them; this only reads and
// remembers.
import '../../../shared/fold.css';

const STORAGE_KEY = 'products.formGroups';

function readChoices() {
  try {
    const found = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}');
    return found && typeof found === 'object' && !Array.isArray(found)
      ? found
      : {};
  } catch {
    // No storage (a private window, blocked data): the page works without.
    return {};
  }
}

function writeChoice(key, open) {
  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ ...readChoices(), [key]: open }),
    );
  } catch {
    // Nothing to keep it in: it holds for this visit.
  }
}

// Open or closed at once, as the page is first drawn: no animation, and no event, so
// that it is not taken for a choice of the person's.
function setOpen(group, open) {
  group.querySelector('.collapse').classList.toggle('show', open);
  const toggle = group.querySelector('.group-toggle');
  toggle.classList.toggle('collapsed', !open);
  toggle.setAttribute('aria-expanded', String(open));
}

export function initFoldableGroups() {
  const groups = [...document.querySelectorAll('[data-fold-group]')];
  if (groups.length === 0) return;
  const choices = readChoices();

  for (const group of groups) {
    const key = group.dataset.foldGroup;
    const inputs = [...group.querySelectorAll('input')];
    const summary = group.querySelector('[data-fold-summary]');
    const count = () => {
      const filled = inputs.filter((input) => input.value.trim() !== '').length;
      summary.textContent = `${filled} / ${inputs.length}`;
    };
    count();
    group.addEventListener('input', count);

    // What the person chose, unless there is something in the group to put right.
    if (
      typeof choices[key] === 'boolean' &&
      !group.querySelector('.is-invalid')
    )
      setOpen(group, choices[key]);

    const body = group.querySelector('.collapse');
    body.addEventListener('shown.bs.collapse', (event) => {
      if (event.target === body) writeChoice(key, true);
    });
    body.addEventListener('hidden.bs.collapse', (event) => {
      if (event.target === body) writeChoice(key, false);
    });
  }

  // A figure the browser refuses (a negative amount) in a closed group would stop the
  // form without a word, for it cannot be shown: the group opens to show it.
  document.getElementById('product-form')?.addEventListener(
    'invalid',
    (event) => {
      const group = event.target.closest?.('[data-fold-group]');
      if (group) setOpen(group, true);
    },
    true,
  );
}
