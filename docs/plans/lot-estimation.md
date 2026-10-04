# Plan: nutrient estimation batch

Status: step 1 (ingredient identity) is done, 2026-10-04; the rest is planned,
not started (written 2026-10-03, after lot 2 merged; revised 2026-10-04: how
an ingredient is linked to its reference changed, see the ground rules,
decisions 8-11 and step 1).
Goal and constraints are in `docs/roadmap.md` ("Estimate a product's
nutrients from its ingredients"); this file is the execution plan.

## Ground rules (decided by the user)

- The estimate is computed in-house. Never use OpenFoodFacts'
  `percent_estimate` or its nutrient estimates.
- CIQUAL is one source used to build reference ingredients, not the truth.
  More sources will be aggregated later, so nothing may assume one source.
- The values declared on the label are the reference. The computation is
  validated against them.
- Ingredient percentages are the label's own figures. The OFF import keeps an
  OFF `percent` only if the product's main ingredient list declares it, as it
  stands or as the number OFF rescaled it from (OFF rescales without saying
  so); see `label_percentages.py`. `Ingredient.percentage` is therefore always
  declared, and a null one is unknown, never estimated.
- Uncertainty is part of the result, not a caveat. Every figure is an
  interval: a declared value is rounded to its last digit (33 % is 32.5-33.5,
  1.4 % is 1.35-1.45), and that margin is carried through to the estimate.
  The margin is read from the stored figure's decimals, trailing zeros
  ignored.
- Every estimate carries a confidence index, and the parts it is built from
  stay visible.
- Consistency problems produce non-blocking warnings.
- An ingredient is its reference ingredient. `Ingredient` stores no name and
  no OpenFoodFacts data (no `off_id`, no CIQUAL codes): only the link to a
  `ReferenceIngredient`, which carries the names (English and French) and is
  curated. OFF data is imperfect, so it never becomes part of these models.
  It travels in `IngredientInput`, before the save, and is used once, to find
  or to create the reference.
- The link is found by the ingredient's normalized name, searched in the
  reference ingredients' own names, which are unique. The label is what the
  user reads on the real product; what OFF recorded of it is checked by hand
  and corrected on OFF when it is out of date.
- When no reference has that name, one is created, marked _to review_, so
  that every ingredient always has one. Curating it is a human task.
- OFF's CIQUAL codes are suggestions, not data: they only seed the source of
  a reference created on the fly (decision 9), and a proxy code never does.
  `IngredientTaxon` is a dictionary used at import (normalized names,
  translations), no longer linked to the models.
- Test product: muesli `3229820794556`. The dev database can be reset.

## Decisions to take at the start of the session

Each one has a recommendation. Validate or adjust them before any code is
written.

1. **CIQUAL version and file.** Checked on 2026-10-04: the 2020 table on
   data.gouv.fr is marked as replaced by Ciqual 2025 (released 2025-11-19,
   recherche.data.gouv.fr, DOI 10.57745/RDMHWY, licence Etalab 2.0): 3,484
   foods, 74 constituents, five UTF-8 XML files (`compo` is 69 MB, `alim`
   1.6 MB, `alim_grp`, `const`, `sources`). Import 2025. Import the XML
   release, which is more stable than the xlsx.
   _Recommendation:_ do not commit the full file. Add a management command
   that takes a path, and commit a small extract (around 10 foods) as a test
   fixture.
2. **Which constituents to import.** _Recommendation:_ all of them, so that
   `Nutrient` rows are created from a mapping table in code (CIQUAL code ->
   code, names, unit, group, parent). Re-importing then adds no new
   decisions.
3. **Aggregating sources into a reference ingredient.** Options:
   - a preferred source;
   - a mean weighted by confidence grade;
   - a median.

   _Recommendation:_ a weighted mean (A=4 … D=1, no grade = 1), keeping the
   min and max as a range. With one source this reduces to that source.

4. **Undeclared percentages.** _Recommendation:_ linear programming with
   `scipy.optimize.linprog`. This adds scipy as a dependency.
   - Constraints:
     - label order means non-increasing percentages;
     - a declared percentage is an interval (see the ground rules), not a
       fixed point;
     - the estimated percentages sum to 100. The declared ones need not: a
       label's 99.4 % is rounding, not an error.
   - Result: for each ingredient, the min and max that are feasible, then a
     point estimate that best fits the declared macronutrients.
5. **Sub-ingredient percentages.** Is a percentage relative to the parent or
   to the whole product? _Recommendation:_ treat it as relative to the
   parent, unless the parent's own percentage is missing and the value is
   larger than any root percentage. Flag the guess as a warning.
6. **Persisting the estimate.** _Recommendation:_ compute on demand at first,
   with no table. Add a `ProductEstimate` cache later if it is slow. That is
   also where Django 6 tasks would come in (see the roadmap).
   - Declared and derived percentages are told apart by where they live, not
     by a flag. `Ingredient.percentage` is the declared figure and the
     estimation never writes to it. Otherwise the next run would read its own
     output as a declared constraint, and saving the product form, which posts
     the ingredient rows back, would turn an estimate into a declared value.
   - A persisted estimate is a snapshot: a `ProductEstimate` (computed at,
     method version, fingerprint of its inputs, confidence components) with
     one child row per ingredient holding `low`, `point` and `high`. It is
     stale as soon as the fingerprint no longer matches the product, the
     reference compositions or the method.
   - The child rows point at the ingredient by its path (ancestors and
     reference), not by foreign key: `_replace_ingredients` deletes and recreates every
     `Ingredient` row on each save, so a cascading key would wipe the
     estimates and a nullable one would orphan them.
   - Letting a user pin an estimate would be a separate override, never a
     declared value.
7. **Confidence index formula.** _Recommendation:_ expose its components
   rather than one opaque score:
   - **coverage:** the share of the mass whose reference has a composition
     (every ingredient has a reference, but a new one may have no source
     food yet);
   - **source quality:** the grades;
   - **percentage uncertainty:** the width of the min-max ranges;
   - **macro agreement:** computed versus declared.

   Add a simple combined 0-1 score on top, documented in code.

8. **Lookup key and normalization of the name.** Decided with the user on
   2026-10-04, and built. The English name is the reference's key, but
   nothing is refused for lacking it. A name is looked up as it is, in
   `name_en` and `name_fr`, whatever the case (accents are not folded: that
   needs a Postgres extension or stored keys, to add if names typed by hand
   show the need). If no reference has it, it is looked up through its
   English correspondence: the names OFF's taxonomy gives for the ingredient's
   OFF id or, for a name typed by hand, for that name when the taxonomy gives
   it a single correspondence ("flocons d'avoine" is "oat flakes"). A
   reference created then takes the correspondence's names; without one, the
   name typed goes in `name_fr` if it is French (by the OFF id's prefix, or
   the language served) and in `name_en` otherwise. Both names are unique when
   filled. A reference may lack `name_en` while it is to review, not once it
   is curated (a check constraint). Normalizing without OFF's taxonomy would
   mean our own dictionary of label wordings: it stays possible, since all of
   it lives in `english_correspondences`.
9. **Source of a reference created on the fly.** _Recommendation:_ if OFF's
   CIQUAL food code (not the proxy one) is that of a known `SourceFood`, it
   is attached to the new reference, which stays _to review_ and counts for
   less in the confidence index. A proxy code is never attached: it is
   written as text in the reference's `description`, with the OFF id, for
   whoever reviews it. This replaces "a human accepts each suggestion": the
   review is of the reference, once, not of each link.
10. **First batch of reference ingredients.** _Recommendation:_ no bulk
    generation to begin with. References come from the products actually
    added (decision 9), so the catalogue follows real use. An admin action
    on `SourceFood`, "create a reference ingredient from the selection",
    covers seeding by hand. Revisit once the first products show how many
    references are missing.
11. **Which CIQUAL foods are left out.** Prepared dishes, and also prepared
    products such as sauces, mayonnaise and stocks (user, 2026-10-04: they
    are not ingredients). The cut is made on the real file, and probably
    needs CIQUAL's sub-groups, not only the top-level `food_group`: the
    codes 11xxx mix salt and spices, which stay, with sauces and stocks,
    which go (seen in OFF's taxonomy: 11058 salt, 11054 mayonnaise, 11001
    stock). Re-importing later to add a group costs nothing: the import is
    idempotent.

## Steps (one commit or more each, tests with each)

1. **Ingredient identity** (done): an ingredient is its reference.
   - Done as planned, with these differences. The lookup is
     `find_references` and the creation `resolve_references`, both in
     batches, in `services/reference_services.py`. The table on the product
     page has a column for the reference's status in place of the reference's
     name, and its CIQUAL column shows the codes of the reference's CIQUAL
     source foods, or OFF's own code for a row not saved yet. Until CIQUAL
     is imported (step 2), a saved ingredient shows no CIQUAL code: OFF's
     code is only in the reference's `description`. Migrations 0004 and 0005
     convert existing ingredients: one reference per distinct name, French
     name from the taxonomy, and a second ingredient that lands on the same
     reference under one parent is dropped.
   - What follows is the plan as written.
   - `Ingredient` loses `name`, `off_id`, `off_ciqual_food_code` and
     `off_ciqual_proxy_food_code`. `reference` becomes required, with
     `PROTECT` (a reference in use cannot be deleted). The unique
     constraints move to (product, parent, reference), and (product,
     reference) for roots.
   - `ReferenceIngredient` gets a status (`to_review`, `curated`) and the
     name rules of decision 8.
   - `IngredientInput` stays the carrier of what a client sends: `name`,
     `percentage`, `sub_ingredients`, plus the OFF hints (`off_id`, CIQUAL
     codes). Nothing of the hints is stored.
   - Service `resolve_reference(item)`: look the name up among the
     references' names, and create a `to_review` reference when none has it
     (names from the input and from the taxonomy's French name, source and
     notes as in decision 9). A link only ever comes from an identical name.
   - `_replace_ingredients` no longer carries links over to the new tree: the
     name finds the same reference again. It keeps its other behaviour: the
     product's ingredients are deleted and recreated on each save, and when
     the same reference comes up twice under one parent the last one wins,
     as it does today.
   - The page shows the reference's name in the language served.
     `IngredientTaxon.display_names` leaves the saved product. It is still
     used to preview an OFF draft, whose rows have no reference yet: the
     preview only looks references up, and creates none.
   - API: `IngredientOut` returns the reference (id, name, status) in place
     of `name` and `off_*`. Update `ingredients-table.js` and the product
     page columns accordingly.
   - Migration. The dev database can be reset (ground rules), so dropping the
     existing ingredient rows is acceptable. Otherwise convert them: one
     reference per distinct name.
   - Do this on a clean tree: it touches files that still carry uncommitted
     work (the label percentages), and the two should be separate commits.
2. **CIQUAL import**: `manage.py import_ciqual <path>`.
   - Leave out prepared dishes and prepared products (decision 11).
   - Create or update the `Source` with its attribution text and version.
   - Upsert `SourceFood` on (source, code), and `SourceFoodNutrient`.
   - Parse values as follows:
     - `-` -> amount NULL;
     - `< x` -> amount x, qualifier `less_than`;
     - `traces` -> amount NULL, qualifier `traces`.
   - Convert decimal commas.
   - Units appear only in the constituent label. Parse them and check them
     against `Nutrient.unit`, and fail loudly on a mismatch.
   - Keep protein on code 25003 (N x 6.25), as seeded.
   - The command is idempotent: a second run changes nothing.
3. **Derived nutrients**: data migration for `NutrientComponent`. To
   re-examine first: Ciqual 2025 gives vitamin A in retinol equivalents
   (51104), total vitamin D (52100) and folates as DFE (56702) directly, so
   only what a source does not give needs deriving (vitamin K is still split
   in K1 and K2).
   - Vitamin A (RE) = retinol x 1 + beta-carotene x 1/6, both in µg.
   - Vitamin K = K1 + K2.
   - Review the CIQUAL list for others, for example niacin equivalents and
     vitamin E.
   - Service: `derived_amount(nutrient, amounts)`. A derived value is
     incomplete, not zero, when a component is missing.
4. **Reference ingredient composition**:
   `reference_composition(ref) -> dict[code, Estimate]`.
   - `Estimate` holds amount, low, high, qualifier, grades and source foods.
   - Aggregation follows decision 3.
   - Admin: show the aggregated composition read-only on
     `ReferenceIngredient`.
5. **Curating the references**.
   - Admin worklist: the references still _to review_, most used first
     (`usages`), with their source foods. What a reference was created from
     (the OFF id, a proxy CIQUAL code) is read in its `description`, where
     creation writes it as plain text.
   - No action to merge two references: the lookup is by identical name, so
     the deleted one would be created again by the next product that uses
     its name. Two names that should be one are fixed in the normalization.
   - Admin action on `SourceFood`: create a reference ingredient from the
     selection (decision 10).
   - Mark a reference as `curated` once checked.
   - The product-page UI for this belongs to lot 3. Admin is enough here.
6. **Percentage estimation**: `estimate_percentages(product)`.
   - Follows decisions 4 and 5.
   - Returns min, point and max per ingredient, plus warnings, for example
     declared percentages that are impossible.
   - Test against the muesli and hand-made trees: all declared, none
     declared, nested.
7. **Nutrient computation**: `estimate_nutrients(product)`.
   - Uses the finest level of each branch whose reference has a composition,
     never a parent and its children together.
   - Amount = sum of percentage x composition / 100, with ranges carried
     from the percentage and source ranges.
   - Coverage is computed per nutrient, because CIQUAL has holes.
8. **Validation and confidence**: compare the computed and declared values
   for the 8 label nutrients. Report the gaps, then build the confidence
   object of decision 7. Warnings stay non-blocking.
9. **Output**: `GET /api/v1/products/{barcode}/estimate`, read-only, for
   signed-in users.
   - Shows, per nutrient, the estimate, its range, coverage and declared
     value.
   - Shows, per ingredient, the declared and the estimated percentage as
     separate fields, and its reference. `declared` is null when the label
     gives none; `estimated` (`low`, `point`, `high`) is always present, and
     for a declared ingredient it is the declared interval, possibly
     narrowed by the constraints. The page shows the declared column as
     editable and the estimated one apart, muted, with its margin.
   - On the existing product page, show a plain table. The real UI comes in
     lot 3.
   - Show the CIQUAL attribution wherever its data appears.
10. **Docs**: remove the done items from `docs/roadmap.md` and update the
    translations (`.po`).

## Out of scope

- Processing losses (cooking, drying) and water loss: keep them as an
  explicit caveat in the output.
- Transformations of a food that change its nutrition (cooking, how it is
  preserved, how foods combine). A real piece of design work, to be done
  later, and the estimation must not assume a composition is always the raw
  one. Cost grows in three levels:
  1. data: CIQUAL already lists cooked and processed foods, so the right
     `SourceFood` is the transformation;
  2. retention factors per (process, nutrient), plus the water lost, which
     concentrates the macronutrients;
  3. parametrised models (an exponential decay depending on temperature and
     time, for vitamin C or the oxidation of fatty acids), for which data is
     scarce: a rare steak or one cooked through, a fat kept for weeks.

  If functions are needed, keep a small catalogue of families written in
  code (factor, decay...) with their parameters in the database, never
  formulas stored as text and evaluated. A transformation would take an
  `Estimate` and return another, with a wider interval, which fits the
  uncertainty rule above.

- Sources other than CIQUAL: the model is ready, but no importer yet.

## Done when

- The muesli gets an estimate, with coverage and confidence, viewable in
  the API and on its page.
- Backend tests, vitest, basedpyright (strict on products) and pre-commit
  all pass.
- A browser check has been done on the muesli.
