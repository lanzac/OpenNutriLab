// The button that asks OpenFoodFacts for the product of the barcode, on the page that
// creates or edits a product (see opennutrilab/templates/products/components/
// off_review.html).
//
// What it finds is set against the form, never poured over it: a value the form has
// not got yet is filled in; when OpenFoodFacts has another value than one the form
// has, the person is shown the two side by side and takes what they choose. The page
// does not reload, so what they typed and did not save stays.
import './off-lookup.css';

/**
 * The list a lookup finds, already read (see OffLookupView in
 * opennutrilab/products/views.py).
 *
 * @typedef {{ barcode: string, text: string, language: string, ingredients: string,
 *   rows: object[], used: [number, number][] }} Label
 */

// A unit that was not chosen is taken for the default until a quantity is typed.
const UNIT_OF = {
  serving_unit: 'serving_quantity',
  package_unit: 'package_quantity',
};
// What the food group of a product that has none is saved as (see ProductForm).
const NO_GROUP = 'Unknown';

/**
 * Whether two values are the same one: figures by what they are worth ("12.50" and
 * "12.5"), anything else as written, not counting the white space around it.
 *
 * @param {unknown} a
 * @param {unknown} b
 * @param {boolean} [numeric]
 */
export function sameValue(a, b, numeric = false) {
  const left = String(a ?? '').trim();
  const right = String(b ?? '').trim();
  if (left === right) return true;
  if (!numeric || left === '' || right === '') return false;
  const x = Number(left.replace(',', '.'));
  const y = Number(right.replace(',', '.'));
  return Number.isFinite(x) && Number.isFinite(y) && x === y;
}

/** How a value of a field reads to a person: a choice by its caption, a figure with its unit. */
function describe(control, value) {
  const text = String(value ?? '');
  if (control instanceof HTMLSelectElement) {
    const option = [...control.options].find((o) => o.value === text);
    return option ? option.textContent.trim() : text;
  }
  const unit = control
    .closest('.input-group')
    ?.querySelector('.input-group-text');
  return unit && text ? `${text} ${unit.textContent.trim()}` : text;
}

function labelOf(form, control, named) {
  if (named[control.name]) return named[control.name];
  const label = control.id && form.querySelector(`label[for="${control.id}"]`);
  return label ? label.textContent.replace('*', '').trim() : control.name;
}

/** Puts a value in a field the way a person would: what listens to the field hears it. */
function setControl(control, value) {
  control.value = value;
  control.dispatchEvent(new Event('input', { bubbles: true }));
  control.dispatchEvent(new Event('change', { bubbles: true }));
}

/**
 * The fields of the form whose value differs from what OpenFoodFacts has.
 *
 * A value OpenFoodFacts has not got is no proposal: it does not empty a field. A
 * `fills` change replaces nothing a person typed or saved.
 *
 * @param {HTMLFormElement} form
 * @param {Record<string, string | null>} fields By name of field.
 * @param {Record<string, string>} [named] Captions of the fields that have no label.
 * @returns {{ kind: 'field', label: string, current: string, proposed: string,
 *   fills: boolean, apply: () => void }[]}
 */
export function fieldChanges(form, fields, named = {}) {
  const adding = !form.elements.namedItem('barcode')?.disabled;
  const changes = [];
  for (const [name, proposed] of Object.entries(fields)) {
    const control = form.elements.namedItem(name);
    if (name === 'barcode' || !control || !('value' in control)) continue;
    if (control.disabled || String(proposed ?? '').trim() === '') continue;
    const numeric = control.type === 'number';
    if (sameValue(control.value, proposed, numeric)) continue;

    const dependsOn = UNIT_OF[name] && form.elements.namedItem(UNIT_OF[name]);
    const noGroup = control.type === 'hidden' && control.value === NO_GROUP;
    const atDefault =
      adding &&
      control instanceof HTMLSelectElement &&
      [...control.options].find((o) => o.defaultSelected)?.value ===
        control.value;
    changes.push({
      kind: 'field',
      label: labelOf(form, control, named),
      current: describe(control, noGroup ? '' : control.value),
      proposed: describe(control, proposed),
      fills:
        control.value.trim() === '' ||
        atDefault ||
        noGroup ||
        Boolean(dependsOn && dependsOn.value.trim() === ''),
      apply: () => setControl(control, proposed),
    });
  }
  return changes;
}

function cell(content) {
  const td = document.createElement('td');
  if (typeof content === 'string') {
    td.textContent = content;
  } else if (content) {
    td.append(content);
  }
  return td;
}

function textBlock(text, nothing) {
  const block = document.createElement('div');
  block.className = text ? 'off-review-text' : 'text-body-secondary fst-italic';
  block.textContent = text || nothing;
  return block;
}

function pictureBlock(src, alt) {
  const image = document.createElement('img');
  image.className = 'off-review-thumb';
  image.src = src;
  image.alt = alt;
  return image;
}

/**
 * @param {{ url: string, labels: Record<string, string> }} config Built server-side (see
 *   product_form_config in opennutrilab/products/views.py).
 * @param {{ text: () => string, load: (label: Label) => void } | undefined} ingredients
 *   The list of ingredients of the form, which takes the list OpenFoodFacts has.
 * @returns {{ lookup: (barcode: string) => Promise<void> } | undefined}
 */
export function initOffLookup(config, ingredients) {
  const form = document.getElementById('product-form');
  const button = document.getElementById('off-lookup');
  const status = document.getElementById('off-lookup-status');
  const review = document.getElementById('off-review');
  const barcodeField = document.getElementById('id_barcode');
  if (!form || !button || !status || !review || !barcodeField || !config) {
    return undefined;
  }
  const { labels } = config;
  const named = {
    group_level_1: labels.groups,
    group_level_2: labels.subgroups,
  };
  const preview = () => document.querySelector('.product-image-preview');
  const hidden = (name) => form.elements.namedItem(name);

  let latest = 0;

  function say(message, failure = false) {
    status.textContent = message;
    status.classList.toggle('text-danger', failure);
    status.classList.toggle('text-body-secondary', !failure);
  }

  function close() {
    review.hidden = true;
    review.replaceChildren();
  }

  /** The changes the list and the photo of the lookup make, besides those of the fields. */
  function otherChanges(answer, barcode) {
    const changes = [];
    const { label } = answer;
    const now = ingredients?.text() ?? '';
    const proposedText = label.text.replace(/\r\n?/g, '\n');
    if (ingredients && proposedText.trim() !== '' && proposedText !== now) {
      changes.push({
        kind: 'text',
        label: labels.ingredientList,
        current: now,
        proposed: proposedText,
        fills: now.trim() === '',
        apply: () =>
          ingredients.load({ ...label, text: proposedText, barcode }),
      });
    }
    const picture = preview();
    if (
      answer.image &&
      picture &&
      hidden('off_image_url')?.value !== answer.image
    ) {
      const none = picture.dataset.placeholder === '1';
      changes.push({
        kind: 'photo',
        label: labels.photo,
        current: none ? '' : picture.src,
        proposed: answer.image,
        fills: none,
        // A photo that is there already is not replaced unless the person says so.
        checked: none,
        apply: () => {
          const offBarcode = hidden('off_barcode');
          if (offBarcode) offBarcode.value = barcode;
          const url = hidden('off_image_url');
          if (url) url.value = answer.image;
          picture.src = answer.image;
          delete picture.dataset.placeholder;
        },
      });
    }
    return changes;
  }

  function rowOf(change) {
    const row = document.createElement('tr');
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.className = 'form-check-input';
    box.checked = change.checked ?? true;
    box.setAttribute('aria-label', change.label);
    const current =
      change.kind === 'photo'
        ? change.current && pictureBlock(change.current, labels.inForm)
        : change.kind === 'text'
          ? textBlock(change.current, labels.nothing)
          : change.current;
    const proposed =
      change.kind === 'photo'
        ? pictureBlock(change.proposed, labels.onOff)
        : change.kind === 'text'
          ? textBlock(change.proposed, labels.nothing)
          : change.proposed;
    row.append(
      cell(box),
      cell(change.label),
      cell(current || labels.nothing),
      cell(proposed),
    );
    return { row, box, change };
  }

  function showReview(changes, apply) {
    const card = document.createElement('div');
    card.className = 'card border-warning';
    const body = document.createElement('div');
    body.className = 'card-body';

    const title = document.createElement('p');
    title.className = 'fw-semibold mb-2';
    title.textContent = labels.title;

    const table = document.createElement('table');
    table.className = 'table table-sm align-middle mb-2';
    const head = document.createElement('thead');
    const all = document.createElement('input');
    all.type = 'checkbox';
    all.className = 'form-check-input';
    all.checked = true;
    all.setAttribute('aria-label', labels.selectAll);
    const headings = document.createElement('tr');
    headings.append(
      cell(all),
      ...[null, labels.inForm, labels.onOff].map((t) => {
        const th = document.createElement('th');
        th.scope = 'col';
        th.textContent = t ?? '';
        return th;
      }),
    );
    head.append(headings);
    const tbody = document.createElement('tbody');
    const rows = changes.map(rowOf);
    tbody.append(...rows.map(({ row }) => row));
    table.append(head, tbody);
    all.addEventListener('change', () => {
      for (const { box } of rows) box.checked = all.checked;
    });

    const wrap = document.createElement('div');
    wrap.className = 'table-responsive off-review-table';
    wrap.append(table);

    const take = document.createElement('button');
    take.type = 'button';
    take.className = 'btn btn-sm btn-primary me-2';
    take.textContent = labels.apply;
    take.addEventListener('click', () => {
      apply(rows.filter(({ box }) => box.checked).map(({ change }) => change));
    });
    const keep = document.createElement('button');
    keep.type = 'button';
    keep.className = 'btn btn-sm btn-outline-secondary';
    keep.textContent = labels.cancel;
    keep.addEventListener('click', () => {
      close();
      say('');
    });

    body.append(title, wrap, take, keep);
    card.append(body);
    review.replaceChildren(card);
    review.hidden = false;
  }

  async function lookup(barcode) {
    const wanted = barcode.trim();
    if (!wanted) {
      window.alert(labels.enterBarcode);
      return;
    }
    latest += 1;
    const ticket = latest;
    // The barcode chosen from a search is the one the form is about from now on.
    if (!barcodeField.disabled) barcodeField.value = wanted;
    close();
    say(labels.asking);
    button.disabled = true;
    try {
      const response = await fetch(
        `${config.url}?${new URLSearchParams({ barcode: wanted })}`,
        { headers: { Accept: 'application/json' }, credentials: 'same-origin' },
      );
      const answer = await response.json().catch(() => ({}));
      if (ticket !== latest) return;
      if (!response.ok) {
        say(answer.error ?? labels.failed, true);
        return;
      }

      // A product's barcode is its identity: only a new one takes the spelling
      // OpenFoodFacts gives it. The list and the photo go with it, whichever.
      const adding = !barcodeField.disabled;
      const barcodeFinal = adding
        ? answer.fields.barcode || wanted
        : barcodeField.value.trim();
      const changes = [
        ...fieldChanges(form, answer.fields, named),
        ...otherChanges(answer, barcodeFinal),
      ];
      const apply = (chosen) => {
        if (adding) barcodeField.value = barcodeFinal;
        for (const change of chosen) change.apply();
        close();
        say(labels.taken.replace('%(count)s', String(chosen.length)));
        for (const notice of answer.notices) {
          const line = document.createElement('div');
          line.className = 'text-warning-emphasis';
          line.textContent = notice;
          status.append(line);
        }
      };

      if (changes.length === 0) {
        if (adding) barcodeField.value = barcodeFinal;
        say(labels.same);
      } else if (changes.every((change) => change.fills)) {
        // Nothing the form has is replaced: there is nothing to choose.
        apply(changes);
      } else {
        say('');
        showReview(changes, apply);
      }
    } catch {
      if (ticket === latest) say(labels.failed, true);
    } finally {
      if (ticket === latest) button.disabled = false;
    }
  }

  button.addEventListener('click', () => lookup(barcodeField.value));
  return { lookup };
}
