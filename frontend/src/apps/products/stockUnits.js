import { fill } from '../../shared/format.js';

// What the inventory counts a product in: grams or millilitres, as a package is, or
// servings when the label names them as things ("1 pot", "1 tranche", "1 bouteille"),
// which are whole and not cut. The server says whether a serving is such a thing
// (`count_noun`, "pot"); the rest is arithmetic on the package and the serving.

/** A count of things written in the language, the way `Intl` does it. */
const number = (value, languageCode) =>
  new Intl.NumberFormat(languageCode).format(Number(value));

/** Two decimals at most, whatever float sum the figure comes from. */
export const cents = (value) => Math.round(value * 100) / 100;

/** A hair over a whole number is that whole number (3 × 0.1 is not 0.3). */
const EPSILON = 1e-6;

/** The word for a number of things: "pot", "pots"; the first word only ("tranches de pain"). */
export function plural(noun, count) {
  if (!(Math.abs(Number(count)) >= 2)) return noun;
  const [first, ...rest] = noun.split(' ');
  let word = first;
  if (!/[sxz]$/i.test(first)) {
    word = /au$/i.test(first) ? `${first}x` : `${first}s`;
  }
  return [word, ...rest].join(' ');
}

/**
 * How many servings a package holds, when it holds a whole number of them (within
 * a fiftieth: 500 g of bread in slices of 35.7 g are 14). Null when the product has
 * no package or no serving, they are not in the same unit, or the number is not whole
 * (a package of 375 g of muesli in servings of 30 g holds 12.5).
 */
export function packageServings(product) {
  const pack = product.package;
  const serving = product.serving;
  if (!pack || !serving || pack.unit !== serving.unit) return null;
  const ratio = Number(pack.quantity) / Number(serving.quantity);
  const whole = Math.round(ratio);
  if (whole < 1 || Math.abs(ratio - whole) > 0.02 * whole) return null;
  return whole;
}

/** How much one package holds in a stock unit, or null when that cannot be told. */
export function packageContent(product, unit) {
  if (unit === 'serving') return packageServings(product);
  const pack = product.package;
  return pack && pack.unit === unit ? Number(pack.quantity) : null;
}

/** The unit a stock is counted in when it is in grams or millilitres. */
const weightUnit = (product) =>
  product.package?.unit ?? product.serving?.unit ?? 'g';

/**
 * The quantity of a stock in another unit, or null when that cannot be told.
 * Servings are whole: a pot that is started is a pot, so grams become the pots they
 * need, rounded up.
 */
export function convertStock(quantity, from, to, product) {
  if (from === to) return quantity;
  const serving = product.serving;
  if (!serving) return null;
  const size = Number(serving.quantity);
  if (to === 'serving' && from === serving.unit) {
    return Math.ceil(quantity / size - EPSILON);
  }
  if (from === 'serving' && to === serving.unit) return cents(quantity * size);
  return null;
}

/**
 * What a stock of a product may be counted in, as options: the weight of a package,
 * and the servings where the label names them. Where a stock is counted already, only
 * the units it can be brought to without losing it.
 */
export function stockUnitOptions(product, current, quantity, labels) {
  const units = [weightUnit(product)];
  if (product.count_noun) units.push('serving');
  if (!units.includes(current)) units.push(current);
  return units
    .filter(
      (unit) =>
        quantity === null ||
        convertStock(quantity, current, unit, product) !== null,
    )
    .map((unit) => ({ value: unit, label: unitLabel(unit, product, labels) }));
}

/** What a unit is called: "g", or "pots" for the servings of a product counted by pot. */
export function unitLabel(unit, product, labels) {
  if (unit !== 'serving') return unit;
  return product.count_noun
    ? plural(product.count_noun, 2)
    : labels.stockServings;
}

/**
 * What a package holds as the list says it: "4 pots de 100 g" where the label names
 * the serving and the package is a whole number of them, else "400 g"; nothing for a
 * product with no package.
 */
export function describePackage(product, labels, languageCode) {
  const pack = product.package;
  if (!pack) return '';
  const count = product.count_noun ? packageServings(product) : null;
  if (count === null) {
    return `${number(pack.quantity, languageCode)} ${pack.unit}`;
  }
  return fill(labels.packageOfServings, {
    count: number(count, languageCode),
    noun: plural(product.count_noun, count),
    serving: `${number(product.serving.quantity, languageCode)} ${product.serving.unit}`,
  });
}

/**
 * The unit a stock starts to be counted in, as the server says it: servings for a
 * product whose serving is a thing that is counted, else the unit of its package.
 */
export function defaultStockUnit(product) {
  return product.count_noun ? 'serving' : (product.package?.unit ?? 'g');
}

/**
 * Where the stock of a product stands, for the list to say it: null when the product
 * is not in the inventory, `uncounted` when it is there and nobody counted it,
 * `used-up` at nothing and `counted` otherwise.
 */
export function stockStatus(product) {
  if (!product.in_inventory) return null;
  const quantity = product.stock?.quantity;
  if (quantity === null || quantity === undefined) return 'uncounted';
  return Number(quantity) === 0 ? 'used-up' : 'counted';
}

/** An amount in a stock unit as it is written: "3 bouteilles", "1 boîte", "270 g". */
export function describeAmount(product, unit, quantity, labels, languageCode) {
  const amount = number(quantity, languageCode);
  if (unit !== 'serving') return `${amount} ${unit}`;
  const noun = product.count_noun
    ? plural(product.count_noun, quantity)
    : labels.stockServings;
  return `${amount} ${noun}`;
}

/** The stock of a product in the inventory as it is written: "3 bouteilles". */
export function describeStock(product, labels, languageCode) {
  const { quantity, unit } = product.stock;
  return describeAmount(product, unit, quantity, labels, languageCode);
}

/**
 * What adding a package to the stock of a product comes to: the quantity it makes and
 * the unit it is in, and how much the package holds, written. Null where the package
 * is not known in the unit the stock is counted in.
 */
export function packageAddition(product, labels, languageCode) {
  const unit = product.stock?.unit ?? defaultStockUnit(product);
  const content = packageContent(product, unit);
  if (content === null) return null;
  const held = Number(product.stock?.quantity ?? 0);
  return {
    unit,
    quantity: cents(held + content),
    text: describeAmount(product, unit, content, labels, languageCode),
  };
}

/**
 * What a stock comes to in other terms, said in a sentence: its weight where it is
 * counted by pot, and the share of a package it is where the package is known
 * ("That is 300 g, 0.25 package."). Empty where there is nothing to add to the
 * quantity itself.
 */
export function describeEquivalent(
  product,
  unit,
  quantity,
  labels,
  languageCode,
) {
  // Nothing counted, or nothing left: there is nothing to put in other terms.
  if (quantity === null || quantity === 0) return '';
  const parts = [];
  if (unit === 'serving' && product.serving) {
    const weight = convertStock(quantity, unit, product.serving.unit, product);
    if (weight !== null) {
      parts.push(`${number(weight, languageCode)} ${product.serving.unit}`);
    }
  }
  const content = packageContent(product, unit);
  if (content !== null) {
    const packages = cents(quantity / content);
    parts.push(
      `${number(packages, languageCode)} ${plural(labels.stockPackage, packages)}`,
    );
  }
  return parts.length === 0
    ? ''
    : fill(labels.stockEquivalent, { amount: parts.join(', ') });
}
