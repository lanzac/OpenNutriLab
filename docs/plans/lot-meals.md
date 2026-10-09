# Plan: servings, meals and the best day

Status: **the eight steps are done** (2026-10-09). Written that day from the user's
request; the user answered decisions 1, 3, 6 and 7 the same day (marked "decided"),
and the others are recommendations they did not object to. The work is on the branch
`feat/meals`, from `main` once `feat/ingredient-forms` was merged into it. What is
left, and what was found on the way, is in "After the batch" at the end.

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
5. **The profile and the needs** (done) (decision 3): the profile and its form, the
   ANSES dataset and its migration, `daily_needs(profile)` giving a minimum, a target
   and a maximum per nutrient. Tested against the documents' own tables.
   - A new app, `opennutrilab.meals`. `Profile` (migration meals 0001): sex, **year**
     of birth (enough for the age bands, and it says less than a date), height,
     weight, physical activity level (a number, with EFSA's levels as help: 1.4
     sedentary, 1.6 moderately active, 1.8 active, 2.0 very active), high menstrual
     losses for a woman, and the two ratio targets with their tolerance (1, 1 and
     0.10 by default). Adults only, neither pregnant nor breastfeeding.
   - **The references are a file, `meals/data/anses_references.json`, read as it is,
     and not loaded by a migration** as this decision first said: they are published
     figures that nothing points to, so a table would only be a copy to keep in step.
     Each figure names its opinion and page:
     - vitamins and minerals from the **2021 opinion** (tables 2 and 3), newer than
       the 2016 table, whose own figures differ (magnesium 420 mg, vitamin D up to
       50 µg);
     - energy shares, sugars, fibre, the LA/ALA ratio below 5 and sodium over
       potassium in moles at most 1 from **ANSES' own diet optimisation of 2016**
       (table 28, page 94): proteins 10-20 %, fat 35-40 %, carbohydrates 40-55 %,
       saturated fat under 12 %, lauric + myristic + palmitic under 8 %, LA at least
       4 %, ALA at least 1 %, EPA + DHA at least 500 mg, sugars under 100 g, fibre
       at least 30 g;
     - EPA and DHA at least 250 mg each, from the **2011 lipid opinion** (table 19).
   - Choices made where the opinions leave one: no upper limit on magnesium (the
     opinion's is on supplements and added salts only); vitamin A's limit is on
     retinol, folic acid's on folic acid alone; niacin's 900 mg (nicotinamide) is
     kept, as the 2016 optimisation did; zinc is the figure for 900 mg/day of
     phytates, as there; sodium is the 2021 opinion's 1500 to 2300 mg, not the 2016
     observed medians; calcium is 1000 mg until 24 and 950 from 25.
   - Not covered: biotin, choline, molybdenum, fluoride and manganese (no table, or
     no CIQUAL value), and water (the meals hold no drinks).
   - **Energy** (`meals/services/energy.py`): the mean of the five equations ANSES
     uses (Schofield, Mifflin, Harris & Benedict, Müller, Henry) times the activity
     level, a day being within 5 % of it, as ANSES' optimisation allows. Checked
     against the report's table 26: within 0.35 % for every equation and band, but
     for Henry's in men of 60 to 69 (1.5 %).
   - The page "Mes besoins" (`/needs/`, in the menu): the profile's form, and the
     needs it gives by group of the catalogue, with each end's kind (RNP, AS, LSS,
     bound of the optimisation) and source, then the ratios and the sources.
   - **The user's profile in the development database**: a man born in 1995, 180 cm,
     61 kg, with **an activity level of 1.7, which was chosen here and is to confirm**:
     office work with walking and 4 hours of sport a week falls between EFSA's 1.6
     and 1.8. It gives 2651 kcal a day (2518 to 2783).
   - Known limits: the niacin reference is in niacin equivalents (tryptophan
     included), which CIQUAL's niacin is not, so niacin looks lower than it is; the
     sugar limit is on sugars less lactose, compared with all sugars; an age from a
     year can be a year off; ANSES worked its energy figures out for a BMI of 22, and
     the profile's own weight is used here (61 kg is a BMI of 18.8).
   - With the user's omega-3:omega-6 of 1 and LA at least 4 % of the energy (11.8 g
     for this profile), a day needs some 12 g of omega-3 or more.
   - To read the opinions' tables the container got `poppler-utils` (apt), which the
     project does not need.
6. **The meals page** (done) (decisions 4 and 8): days, meals, the API, the React
   page; totals per meal and per day against the needs, the two ratios, intervals and
   coverage.
   - `Meal` (user, date, one of breakfast, lunch, snack, dinner; once per user, date
     and kind) and `MealItem` (a product, a quantity, and a unit: servings of the
     product or grams; a product once per meal), migration meals 0002. **A day has no
     row of its own**: it is the date, and its four meals are made when something is
     first put in them.
   - Only a product of **the user's inventory** can be put in a meal; servings need
     a product that has a serving (grams do not). A product deleted leaves the meals
     it was in.
   - `services/day_report.py`: a portion is some grams of a product, which brings
     its composition (step 3) times grams over 100, and a meal or the day is the sum.
     Every total keeps the amount, its interval (sums of the portions' own) and its
     **coverage**, the share of the mass whose product gives a value. A nutrient a
     product does not give counts as nothing, so a total is what is at least there,
     and its upper end is unknown (None) unless every product gives it.
   - Each need is set against the day's total with a verdict: below, within or above,
     **and whether the whole interval says the same** (`certain`). A day is below
     for certain only when even its upper end is, and within for certain only when
     the whole interval is. A need on a sum (EPA + DHA, lauric + myristic + palmitic)
     adds the totals; the ratios (LA over ALA, sodium over potassium in moles, and
     the user's DHA:EPA and omega-3:omega-6) are worked out from the totals with an
     interval of their own, and a ratio over nothing is "unknown".
   - API: `GET /api/v1/meals/{day}` (the four meals, their items and totals, the day's
     totals, the needs with their verdicts, the ratios; needs and ratios are null
     without a profile), `POST /api/v1/meals/{day}/{kind}/items`, `PATCH` and
     `DELETE /api/v1/meals/items/{id}`. **A write answers with the whole day it
     changed**, which the page shows as it is: no figure is worked out in the browser.
     Another user's item is not found (404); a product not in the inventory or
     servings of a product with none are 422; a product already in the meal is 409.
   - The page "Repas" (`/meals/`, in the menu, a React page in its own Vite entry,
     `meals`): the date with the day before and after, four cards (the products with
     quantity and unit, what the meal brings: energy in kcal, proteins, fat,
     carbohydrates, fibre, omega-3, omega-6, each with its interval and coverage on
     hover), and under them the day's table by group with total, interval, need,
     status and coverage, then the ratios. The labels come from the server, as on the
     inventory page.
   - **The sodium of a composition follows the salt the label declares** (a fix
     found with this page, in `stored_estimates`, commit 1626a5f): the gnocchi
     declare 0.6 g of salt per 100 g but their estimate said 7.1 g, so the day showed
     8,774 mg of sodium. Salt is sodium times 0.0025, so what the label declares of
     the salt is what it declares of the sodium (400 mg for each gram, with its
     rounding), unless it declares the sodium itself.
   - **Known limits, found on the development products**:
     - the estimate's _point_ can lie far from the label for a nutrient that is
       declared: for the gnocchi, the "sel" ingredient's share is poorly bounded.
       Where the label declares the nutrient, the meals use the label; chloride, which
       no label declares, still takes the estimate (13.5 g in a day of 431 g of food),
       and is shown as not certain (coverage 39 %, no upper end);
     - the vegetarian balls have no estimate, so a meal counts them by their eight
       label values only;
     - the energy shares are in grams at the person's energy need, not at the day's
       own energy (within 5 %, they differ by as much).
   - 74 tests in the app and 25 on the page (Vitest); checked in Chromium on the
     development products, in French, with no console error.
7. **The optimiser** (done) (decision 5): the service, its endpoint, a "propose a day"
   button. Tested on small made-up cases whose optimum is known, then on the
   development inventory.
   - `services/optimiser.py`: a mixed-integer linear programme solved by HiGHS
     through `scipy.optimize.milp`. For each product and each meal it may be in, a
     whole number of **steps**: half a serving for a product that has one, 10 g for
     one that has not. The amounts are the points of the products' compositions
     (the label where it declares, the estimate for the rest: step 3).
   - **Every target is soft**, so that there is always an answer. A lower end is
     `amount / low + shortfall >= 1`, an upper end `amount / high - excess <= 1`:
     a shortfall or an excess is the share of the need that is missed, whatever the
     nutrient's unit, and costs its weight. Weights: **energy 10** (a day of 1,000
     kcal that meets every vitamin is not a day), **need 1**, **ANSES' ratios 1**,
     **the user's own ratios 3**, the energy of each meal 1.
   - The energy of the day is held to the person's, within 5 %; the energy of each
     meal near its share (25, 35, 10 and 30 %) **within 25 %**.
   - A ratio is linear (`numerator - high x denominator <= 0` and
     `numerator - low x denominator >= 0`) and its violation is taken over what the
     denominator is at the need (EPA is half of the need for EPA + DHA, omega-6 is
     linoleic acid's), so that a ratio costs the same whatever its unit.
   - **A ratio can be kept by taking none of either**: DHA:EPA is 1:1 for 0 g of each.
     What stops it is the need for EPA and DHA, and the weights say which gives way
     (tested both ways: the ratio weighed little, the need is met at 2:1; weighed
     much, no fish oil at all).
   - A small cost for each product used (0.03) and for each product in each meal
     (0.01), so that a day is not twenty products or the same one in four places.
     The solver gets 20 s and stops within 0.5 % of the best.
   - **Limits per product** (the fields step 4 left to this one): the meals a product
     may be in and the most of it a day, in servings or in grams, in `ItemLimits`
     (meals 0003, in the `meals` app and not on `InventoryItem`, as `meals` depends
     on `products` and not the other way round). Without them a product may be in any
     meal, up to 6 servings and never more than 500 g.
   - `services/proposals.py` turns the inventory into candidates (a product with no
     energy value is left out and named), and the API gives `POST
/api/v1/meals/{day}/propose`, which **writes nothing** and answers with the day
     it would make as a report (items with no id), and `PUT /api/v1/meals/{day}`,
     which puts a list of items in place of the day's meals, all or nothing. `GET`
     and `PUT /api/v1/meals/limits/` serve and set the limits.
   - The page: a "Proposer un jour" button, a preview (the four meals read only and
     the day's table), "Utiliser ce jour" (asking first when the day has something in
     it) or "Fermer", and, under the day, the limits of each product. A proposal is
     dropped when the day changes.
   - **On the development inventory** (5 products, bars only at the snack and at most
     2 servings): solved to optimality in 0.04 s, 2,595 kcal (2,518 to 2,783), proteins,
     carbohydrates, fibre and sugars within their ends, and the misses the inventory
     cannot fix: EPA and DHA (0.01 g of 0.5), most vitamins, calcium, iodine, selenium,
     omega-3 over omega-6 at 0.23 (target 1), sodium a little above 2,300 mg, DHA over
     EPA at 1.7. **These are what step 8 is to suggest**.
   - Known limits: the plan ignores what is already in the day; it is solved in the
     request (20 s at most), which will want a background task if the inventory grows;
     it has no idea of a meal (the vegetarian balls came out at breakfast), which the
     limits are for; the amounts are the estimate's points, so a day can differ from
     its report by the intervals it shows; a product with no energy value is left out.
   - 21 tests of the optimiser (known optima: a need only one product can meet, a
     limit, a cap, the meals a product may be in, steps in servings, the ratios both
     ways, determinism, what the solver may answer), 17 on the proposals and the API,
     13 on the limits; 16 on the page, 3 mutations of its behaviour checked to fail.
8. **Suggestions** (done) (decision 6).
   - `services/suggestions.py`, `POST /api/v1/meals/{day}/suggest`: the best day from
     the inventory is worked out, the needs and ratios it misses are the **gaps**
     (lower ends it does not reach; a ratio it is under, which raises the numerator,
     or over, which raises the denominator; no gap for energy, sodium or chloride,
     which salt would meet), and **foods of the CIQUAL table** that would close them
     are looked for, at most a few: the day is worked out again with them among the
     candidates as **new** foods, which cost 0.15 more than the inventory's, at most
     4 of them. Each suggestion says how much, in which meal (one, to be got and
     eaten), and what it closes (the amount, and the share of what the day should
     bring, "covers the need" above 1), with the link to its CIQUAL sheet. A
     suggestion is a _kind of food_, not a product: the product is for the user to
     find. **Nothing is written.**
   - **Not suggested**: infant foods, alcoholic drinks, waters, salts and the
     "special diet" foods; a food with no energy. Every other food of the table may
     be (omnivore, as decided). The most of a food in a day goes by its group and
     sub-group: 30 g for fats, 20 g for fish oils, 50 g for nuts and seeds, 200 g for
     meat and fish, 100 g for sweets, 250 g otherwise; a food that is at most 50 g a
     day is counted in 5 g, the others in 10 g.
   - **Two goes**, found by trying (the day with 72 foods in it did not finish in
     30 s, and fewer foods gave worse days: 2.3 against 0.9): first the foods are
     chosen, with the inventory in any quantity and no meal for the new foods, in 8 s
     and within 2 %; then the day is worked out for those alone, in whole steps and
     each food in one meal, in about a second. Relaxing every whole number to choose
     the foods was tried and dropped: it named bad foods (2.0 against 0.9). The new
     foods' quantities are numbers, rounded to a step for the page.
   - The first look is on the foods' exact values for the nutrients that are missed
     (0.16 s for the whole table), and only the few that are kept have their
     composition read in full, with its intervals (`food_composition`).
   - The day with them is reported as the others are, the suggested foods being items
     that are not saved (`GenericItem`, a key `ciqual:<code>`), with their sheet.
   - The page: a "Suggérer des aliments" button, the foods with what they close, a
     caution (composition only: no contaminants, no excess of one thing, no cooking,
     no taste), and the day with them, folded. 4 foods in 9.9 s on the page.
   - **On the development inventory** (5 products): 18 of the 42 needs and ratios
     missed, 4 with **cod liver 60 g, swordfish 120 g, red pepper 250 g and skimmed
     milk powder 50 g**, and the user's two ratios met: **DHA:EPA 1.08 and
     omega-3:omega-6 0.93**. Still missed: retinol 3,114 µg (the liver; the limit is
     3,000), folates (312 of 330), vitamin E (9.3 of 10) and sodium (2,374 of 2,300).
   - 23 tests of the foods, the gaps, the choice and the API, 5 of the new foods in the
     optimiser, 10 on the page (two mutations of the "dropped when the day changes"
     were found _not_ to fail with the first tests, which were then made to wait for
     the new day).

## After the batch

What the eight steps leave open, for the user to say:

- **The activity level** of the user's profile is 1.7, chosen between EFSA's 1.6 and
  1.8: to confirm.
- **Reaching omega-3:omega-6 of 1:1 is a lot of omega-3.** With ANSES asking for at
  least 4 % of the energy as linoleic acid (11.8 g), 1:1 means some 12 g of omega-3 a
  day, which the suggestions meet with 60 g of cod liver and 120 g of swordfish. That
  is the target's price, not a bug: the page says so by showing the retinol it brings.
  Whether to loosen the ratio, or to take the linoleic acid at ANSES' lower bound, is
  the user's.
- **The estimate's point can lie far from the label** for a nutrient the label
  declares (the gnocchi's salt: 7.1 g against 0.6 g). The meals use the label where it
  declares, and the sodium follows its salt, but chloride, which no label declares,
  still takes the estimate and is shown as not certain. A better point for the
  estimate would fix it at its source.
- **The vegetarian balls have no estimate** (their declared percentages and the order
  of their ingredients contradict each other), so a meal counts them by their eight
  label values.
- **The optimiser has no idea of a meal**: it put the balls at breakfast. The limits
  per product are for that, and could start from the product's category.
- The proposal and the suggestions run in the request (20 s at most, 10 s in practice):
  a background task (Django 6, see the roadmap) would be better once the inventory is
  large.
- Not done, as said: stock, generic foods in the inventory, other diets, losses in
  cooking.

## Out of scope

- Generic foods without a barcode (a loose apple), and the portions they would need.
- Diets other than omnivore.
- Stock levels, shopping lists, prices.
- Losses in cooking and processing (already on the roadmap).
- Variety from one day to the next, taste, several people at one table.
- Pregnancy, breastfeeding, children: the references are for adults.
