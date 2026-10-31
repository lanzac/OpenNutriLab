// The food groups a product list is cut into: the two levels OpenFoodFacts files
// a product under (Product.group_level_1 and group_level_2), the second inside
// the first.

// A product with no group, or one OpenFoodFacts files under "unknown".
const UNCLASSIFIED = '';

const keyOf = (value) => {
  const key = (value ?? '').trim();
  return key.toLowerCase() === 'unknown' ? UNCLASSIFIED : key;
};

/**
 * The products cut into groups and, in each, subgroups; both sorted by the name
 * they are shown under, the unclassified ones last, and the products by name.
 *
 * A group's subgroups are titled only when it has at least one that is known:
 * a group whose products have no subgroup is a plain list.
 *
 * @param {Array<{ name: string, group_level_1?: string, group_level_2?: string }>} products
 * @param {{ names: Record<string, string>, uncategorised: string, locale: string }} options
 *   `names` maps the words the groups are stored with to the ones shown (a group
 *   it does not know is shown as stored); `uncategorised` names the unclassified.
 * @returns {Array<{
 *   key: string, name: string, count: number, titled: boolean,
 *   subgroups: Array<{ key: string, name: string, products: object[] }>,
 * }>}
 */
export function groupProducts(products, { names, uncategorised, locale }) {
  const nameOf = (key) =>
    key === UNCLASSIFIED ? uncategorised : (names[key] ?? key);
  const byName = (a, b) =>
    (a.key === UNCLASSIFIED) - (b.key === UNCLASSIFIED) ||
    a.name.localeCompare(b.name, locale);

  const groups = new Map();
  for (const product of products) {
    const groupKey = keyOf(product.group_level_1);
    const subKey = keyOf(product.group_level_2);
    if (!groups.has(groupKey)) groups.set(groupKey, new Map());
    const subgroups = groups.get(groupKey);
    if (!subgroups.has(subKey)) subgroups.set(subKey, []);
    subgroups.get(subKey).push(product);
  }

  return [...groups]
    .map(([key, subgroups]) => ({
      key,
      name: nameOf(key),
      count: [...subgroups.values()].reduce((n, list) => n + list.length, 0),
      titled: [...subgroups.keys()].some((subKey) => subKey !== UNCLASSIFIED),
      subgroups: [...subgroups]
        .map(([subKey, list]) => ({
          key: subKey,
          name: nameOf(subKey),
          products: [...list].sort((a, b) =>
            a.name.localeCompare(b.name, locale),
          ),
        }))
        .sort(byName),
    }))
    .sort(byName);
}

/**
 * Where a product is filed, said as a path: "Boissons › Boissons sucrées", or just the
 * group where it has no known subgroup; empty for a product that is not classified.
 */
export function groupPathOf(product, { names }) {
  const known = [product.group_level_1, product.group_level_2]
    .map(keyOf)
    .filter((key) => key !== UNCLASSIFIED);
  return known.map((key) => names[key] ?? key).join(' › ');
}
