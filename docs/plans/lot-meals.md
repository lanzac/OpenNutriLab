# Plan: servings, meals and the best day

Status: planned, nothing built. Written 2026-10-09 from the user's request of that
day; the user answered decisions 1, 3, 6 and 7 the same day (marked "decided"), and
the others are recommendations they did not object to. Work goes on the branch
`feat/meals`, from `main` once `feat/ingredient-forms` was merged into it.

## Why (the user's request, 2026-10-09)

- **A serving for each food**: a slice of bread, a bowl of cereal, an apple for an
  apple. OpenFoodFacts gives it for products.
- **A new page to make up meals**, showing what each meal brings (energy,
  macronutrients, vitamins, minerals, fatty acids...) and what the whole day brings.
- **In the end, a tool that finds the best combination** for each meal and for the
  day, from the foods in the inventory, to meet the needs of an adult of a given
  height and weight (for instance 180 cm and 61 kg), with two targets of the user's
  own: **DHA:EPA 1:1** and **omega-3:omega-6 1:1**.
- **When the inventory cannot meet the targets, suggestions** of what would.

## What the data says (checked 2026-10-09)

- **OpenFoodFacts' serving.** `serving_size` is a free text, `serving_quantity` and
  `serving_quantity_unit` are OFF's reading of it, `product_quantity` is the size of
  the package. On the five products of the development database:
  - bread 3228857002245: `35.7 g (1 tranche)`;
  - gnocchi 3270160860333: `300 g` (the package is 900 g);
  - protein bars 5060088700112: `45 g`;
  - vegetarian balls 3270160101245: `400 g`, which is the whole package;
  - muesli 3229820794556: **nothing**.

  The `*_serving` nutriments are OFF's own sums (per 100 g times the serving) and are
  not read, as no OFF computation is.

- **Nothing of it is stored today**: `OFFProductSchema` reads none of these fields
  and `Product` has no serving.
- **The inventory is the product list**: products with a barcode, shared by every
  user. A loose apple is no product. The only generic foods are the reference
  ingredients (curated, linked to CIQUAL foods), which nothing lets one eat.
- **No source of portions for generic foods was found.** CIQUAL gives none. The
  INCA 3 open data (ANSES, data.gouv.fr) was not seen to hold a table of portions.
  The GEMRCN weights are for school and hospital catering. So a generic food's
  portion is entered by hand, at first.
- **Fatty acids.** The catalogue has linoleic (LA, 18:2 n-6), arachidonic (AA, 20:4
  n-6), alpha-linolenic (ALA, 18:3 n-3), EPA and DHA, from CIQUAL. There is no
  omega-3 or omega-6 total: they are derived nutrients to add, as vitamin K was
  (omega-3 = ALA + EPA + DHA, omega-6 = LA + AA). CIQUAL has no DPA, GLA or SDA, so
  both totals are a little under the truth.
- **The inventory as it is cannot meet either target.** From the estimates of the
  four products that have one, per 100 g: EPA + DHA between 1 and 4 mg, and LA/ALA
  of 2.0 (bread), 8.6 (muesli), 11 (gnocchi) and 250 (bars). The vegetarian balls
  have no estimate at all (to look into on its own). So suggestions are needed from
  the first day.
- **What CIQUAL has for those targets.** Every food rich in EPA and DHA is a fish or
  a fish oil (salmon oil 18.2 g DHA and 13 g EPA per 100 g, sardine oil 10.7 and
  10.1, cod liver oil 11 and 6.9); there is no algae oil. For ALA: linseed oil 53.4
  g, camelina oil 36.4, linseed about 20, chia 17.8, hemp oil 16.6, walnut oil 11.9.
  A vegetarian or vegan source of EPA and DHA needs a food CIQUAL lacks, made with
  the custom-food skill.
- **Reference values.**
  - ANSES (France): vitamins and minerals in the opinion of March 2021
    (NUT2018SA0238Ra), fatty acids in the 2010 opinion on lipids, read through
    secondary sources only so far: total fat 35 to 40 % of energy, LA 4 %, ALA 1 %,
    DHA 250 mg/day, EPA 250 mg/day, omega-6/omega-3 below 5. **To copy from the
    primary documents at the step, not from these summaries.**
  - EFSA (EU): the DRV Finder, gathered in a 2018 EFSA Journal summary; no export of
    its data was confirmed.
- **The user's 1:1 omega-3:omega-6 is far from ANSES's "below 5".** Reaching it means
  adding omega-3 (linseed, camelina oil...) much more than removing omega-6, if the
  LA reference is kept.
- **The whole problem is linear.** A ratio target is linear (omega-3 = omega-6 is
  omega-3 - omega-6 = 0, and 1:1 within 10 % is two inequalities), so the best day is
  a mixed-integer linear programme, which `scipy.optimize.milp` (HiGHS, already a
  dependency) solves.
- **Working an estimate out takes about a second per product.** A day drawn from 20
  foods would take 20 seconds, so the compositions have to be stored: the roadmap's
  "cache" item becomes needed here.

## Decisions

1. **What the inventory holds** (decided 2026-10-09). **Products with a barcode
   only, for now**, as everywhere else in the project; generic foods (a loose apple)
   come later. **Each user has an inventory of their own**, `InventoryItem` (user,
   product, the meals it may appear in, a most per day), apart from the product
   catalogue, which stays shared.
2. **Where a product's serving comes from.** Recommended: from `serving_size`, read
   by this project as the ingredients are, strictly: `<number> g` or `<number> ml`,
   with an optional parenthesis taken as the serving's name (`35.7 g (1 tranche)` is
   35.7 g, "1 tranche"). Anything else is left empty with a notice, and the user
   enters the serving on the product's form. OFF's `serving_quantity` is not read.
   A serving that is the whole package (the balls' 400 g) is kept as it is. A
   serving in ml counts as the same number of grams, said on the page (densities
   later).
3. **The profile and the needs** (decided 2026-10-09). A profile per user: sex,
   date of birth, height, weight, level of physical activity. Energy need = basal
   metabolism (the equation ANSES uses, to identify) times the activity level.
   **The ANSES references**, kept as a dataset in the repository with their source
   and loaded by a migration, as the additives are; their upper limits as maximums;
   EFSA's only for what ANSES lacks. The two ratios are targets of the profile, with
   a tolerance (10 % by default).
   - **The user's own profile, the first case to check**: a man of 31, 180 cm and
     61 kg, office work (sitting), walking regularly, 4 hours of sport a week. How
     that description becomes an activity level is to settle at step 5, from the
     categories ANSES uses.
4. **Days and meals.** Recommended: a day is a date, made of meals (breakfast, lunch,
   snack, dinner by default), each a list of foods with a number of servings (or
   grams for a food without one). The optimiser fills a date; copying a day comes
   later.
5. **What "best" means.** Recommended: every target is soft (each nutrient between
   its reference and its upper limit, energy within 5 % of the need and split
   between the meals, 25/35/10/30 % by default, the two ratios), each missed one
   costing its relative gap times a weight (1 by default), plus a small cost per
   food used. So there is always an answer, the closest day, and what it misses is
   shown. Servings are whole or halves for a food that has one, steps of 10 g for
   one that has not. The point figures of the estimates are optimised; the page
   shows the result's intervals and coverage, as everywhere.
6. **Suggestions.** Recommended: when a target is missed, solve again with the CIQUAL
   foods added as candidates, each with a cost for being new, at most a few of them,
   and show each suggested food, how much of it the day would need and which gaps it
   closes. Generic foods rather than products, since a label rarely declares EPA or
   DHA: the user then picks a product of that kind. **Omnivore by default**
   (decided 2026-10-09): every CIQUAL food may be suggested. A diet on the profile
   (pescetarian, vegetarian, vegan), filtering through CIQUAL's food groups, comes
   when the user asks for it.
7. **Stock** (decided 2026-10-09): later, not in this lot. The inventory says what
   is there, not how much is left.
8. **The page.** Recommended: a React page (its own Vite entry) on a new API (foods
   of the inventory with their composition per serving, days and meals, needs,
   optimise, suggest), which goes the way of the SPA the project aims at.

## Steps (one commit or more each, tests with each)

1. **A product's serving** (done): read and parse `serving_size` (decision 2), the
   fields on `Product` (migration), the product form, the product's page. Done when
   the bread reads 35.7 g "1 tranche" and the muesli has none.
   - `Product.serving_quantity` (2 decimals), `serving_unit` (g or ml) and
     `serving_name`, migration 0016, with a check that a serving has a quantity
     and a unit or nothing at all. `services/servings.py`, `read_serving`, reads
     the three forms of decision 2, in g (also written gr, gram, gramme...), ml, cl
     and l (the last two as ml).
   - On the form, three fields under the description, filled by a lookup (a new
     product, "Reset data"), as the declared values are, outside the model's
     fields. A text that is not read is said in a notice and leaves the field as it
     was. **No notice when OpenFoodFacts has no serving**, unlike what this step
     first said: the empty field says it, and on a reset the serving entered by
     hand is kept, which a notice to enter it would contradict.
   - The API serves `serving` (null when there is none) and takes it on create and
     update; on update, left out it is not touched and null removes it, the one
     field where null means that.
   - Measured on 400 French products from OpenFoodFacts (2026-10-09): 343 have a
     `serving_size`, 305 of them are read (89 %), and none differs from
     OpenFoodFacts' own `serving_quantity`. The 38 not read give two quantities
     (powder and milk), a parenthesis within the parenthesis, a number without a
     unit, or no quantity at all.
   - In the development database (migrated to 0016), the servings of the four
     products that OpenFoodFacts gives one for were filled in through the service:
     bread 35.7 g "1 tranche", gnocchi 300 g, bars 45 g, vegetarian balls 400 g.
     The muesli has none.
2. **The omega-3 and omega-6 totals** (done).
   - **Not derived food by food as vitamin K is**, unlike what this step first said.
     A derivation gives no total when a part is missing, and in CIQUAL 2025 that is
     most foods: of 2,983, 1,584 give ALA, EPA and DHA, and 1,423 give LA and AA.
     Among the others are camelina oil (no EPA, DHA or AA) and chia seed (no AA),
     the richest in ALA after linseed, and 122 meats, eggs and fish that give one of
     EPA and DHA only. Derived food by food, camelina oil would bring no omega-3.
   - So they are **sums of a product's own amounts** (`derived_nutrients.SUMS`,
     worked out in `nutrient_estimation.nutrients_of`): each part counts where it is
     known; the range is the sum of the parts' ranges, with an upper end only when
     every part has one; the coverage is the share whose ingredients give every
     part; the quality in the confidence is the worst part's.
   - `omega_6` "Oméga-6 (LA + AA)" and `omega_3` "Oméga-3 (ALA + EPA + DHA)", in g,
     under the polyunsaturated fatty acids and listed before their parts, are
     created by `ensure_derivations`, which the CIQUAL import runs. They were
     created in the development database by running it by hand. CIQUAL has no DPA,
     GLA or SDA, so both are somewhat under the truth.
   - On the development products, per 100 g: bread omega-6 2.41 g and omega-3
     1.19 g; muesli 3.89 and 0.45, with its omega-6 covered for 35 % only (AA is
     missing for most of its ingredients); gnocchi 0.48 and 0.044; bars 4.79 and
     0.023.
3. **The stored composition of a product** (done), per 100 g (amount, low, high,
   coverage per nutrient), from its estimate; worked out again when the product, its
   ingredients or a reference it uses changes, and by a command.
   - `ProductEstimate` (one per product: when it was worked out, and whether it is
     stale) and `EstimatedNutrient` (amount, low, high, coverage, confidence score),
     migration 0017. `services/stored_estimates.py`: `kept_estimates(products)`
     reads them back and works out again those stale or missing; `work_out` keeps a
     product's; a product the solver fails on is kept with no nutrient, and logged.
   - **Stale, by signals**: a change to a product's ingredients or declared values
     marks its own; a change to anything a composition is made of (references,
     preparations, additives, source foods and their values, the catalogue,
     derivations, and the links between them) marks them all, since finding the
     products it touches would take as long as working them out again. The CIQUAL
     import, which writes in bulk and so tells no signal, marks them itself.
     `refresh_estimates` works out the stale and the missing (`--all`: every one).
   - Measured before choosing: reading a product from the database is 30 to 50 %
     of working its estimate out (0.04 to 0.35 s of 0.26 to 0.46 s), so checking
     a fingerprint of what it is made of would cost almost as much as working it
     out again.
   - **A product's composition** for what follows, `compositions(products)`: the
     label's figure where it declares one, within its rounding and covering the
     whole product, and the estimate for the rest. The label is the reference for
     the product.
   - Development database (migrated to 0017): the five estimates worked out in
     3.8 s, and the five compositions read back in 0.02 s. The vegetarian balls
     have no estimate (their label's declared percentages and the order of their
     ingredients contradict each other), so meals count them by their label only.
4. **Each user's inventory** (done) (decision 1): `InventoryItem`, adding a product
   to it and taking it out from the product list, and a view of one's own inventory.
   - `InventoryItem` (user, product, when it was added; once per user and product),
     migration 0018, in the products app so that the list of products can say what
     is in it. `services/inventory.py`. **The meals an item may appear in and its
     most per day are left to the optimiser (step 7)**, which is what reads them,
     unlike what decision 1 put on it.
   - API: `GET /api/v1/inventory/`, `PUT` and `DELETE /api/v1/inventory/{barcode}`
     (both change nothing when there is nothing to change), and `in_inventory` for
     the user asking on each product of `GET /api/v1/products/`.
   - **A product created, by the page or the API, goes into the inventory of whoever
     created it**: adding a product is what one does with one at hand.
   - The page "Inventaire" shows the user's inventory first, and every product on
     request ("Mon inventaire" / "Tous les produits"), each with a button to put it
     in or take it out; an empty inventory says how to fill it.
   - Development database (migrated to 0018): the five products are in the
     inventory of its one user, `admin`, who added them.
5. **The profile and the needs** (decision 3): the profile and its form, the ANSES
   dataset and its migration, `daily_needs(profile)` giving a minimum, a target and
   a maximum per nutrient. Tested against the documents' own tables.
6. **The meals page** (decisions 4 and 8): days, meals, the API, the React page;
   totals per meal and per day against the needs, the two ratios, intervals and
   coverage.
7. **The optimiser** (decision 5): the service, its endpoint, a "propose a day"
   button. Tested on small made-up cases whose optimum is known, then on the
   development inventory.
8. **Suggestions** (decision 6).

## Out of scope

- Generic foods without a barcode (a loose apple), and the portions they would need.
- Diets other than omnivore.
- Stock levels, shopping lists, prices.
- Losses in cooking and processing (already on the roadmap).
- Variety from one day to the next, taste, several people at one table.
- Pregnancy, breastfeeding, children: the references are for adults.
