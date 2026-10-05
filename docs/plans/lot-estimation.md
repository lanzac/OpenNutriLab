# Plan: nutrient estimation batch

Status: steps 1 (ingredient identity), 2 (CIQUAL import), 3 (derived
nutrients), 4 (composition of a reference), 5 (curating the references), 6
(percentage estimation) and 7 (nutrient computation) are done, 2026-10-04, and
8 (validation and confidence) and 9 (output), 2026-10-05; the rest is planned,
not started
(written 2026-10-03, after lot 2 merged; revised 2026-10-04: how an ingredient
is linked to its reference changed, see the ground rules, decisions 8-11 and
step 1; which composition counts for a branch changed, see step 7).
Goal and constraints are in `docs/roadmap.md` ("Estimate a product's
nutrients from its ingredients"); this file is the execution plan.

## Ground rules (decided by the user)

- The estimate is computed in-house. Never use OpenFoodFacts'
  `percent_estimate` or its nutrient estimates.
- CIQUAL is one source used to build reference ingredients, not the truth.
  More sources will be aggregated later, so nothing may assume one source.
- The values declared on the label are the reference. The computation is
  validated against them.
- **Ingredients are read from the label's text, and nothing else is trusted**
  (decided 2026-10-04). OpenFoodFacts' own parsing of the list drops what its
  taxonomy has no word for: on the muesli it turned "Flocons de soja" into
  "soja", "Fruits rouges lyophilisés" into "Fruits rouges" and left out
  "Graines de sarrasin", and those words tell flakes from beans and
  freeze-dried from raw. So `ingredients_text` is read here
  (`services/label_parser.py`), with its language, and OFF's `ingredients` are
  not read at all. Percentages are therefore the label's own figures as they
  are written: `Ingredient.percentage` is always declared, and a null one is
  unknown, never estimated. Nothing is corrected or guessed: a text that looks
  badly read (brackets that do not match, a letter taken for a digit, the
  nutrition table in the list, a sentence for an ingredient, an empty place
  between commas) gives no ingredient and a warning that says why, and the
  text is corrected on OpenFoodFacts, then the product loaded again.
  Percentages over 100 in total are only a warning.
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
  `IngredientTaxon` is a dictionary (the English and French names of what a
  label names, and a CIQUAL hint), no longer linked to the models: it gives a
  wording its English name when it knows it, and nothing is guessed when it
  does not.
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
   `scipy.optimize.linprog`. This adds scipy as a dependency (accepted by the
   user on 2026-10-04, with numpy; `scipy-stubs` for the types, in the dev
   group).
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
2. **CIQUAL import** (done): `manage.py import_ciqual [--path DIR]`.
   - Done as planned, with these differences. The file is CIQUAL 2025, read
     from a directory of the four XML files, or downloaded to a temporary one
     (about 70 MB, several minutes), never committed. The values keep up to six
     decimals, and a value's minimum and maximum are stored when the source
     gives them (19 % of the numbers). A food has a sub-group as well as a
     group. 72 of the 74 constituents are nutrients (`off_key` left empty on
     the new ones, since the OFF import reads every nutrient that has one):
     the two in kcal repeat the kJ ones. The exclusions are the groups 00 and
     01, the sub-group 1001 and 16 single foods: 501 left out, 2,983
     imported, 214,776 values, in under 30 seconds. The code is in
     `services/ciqual_import.py` and `services/ciqual_constituents.py`.
   - What follows is the plan as written.
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
3. **Derived nutrients** (done): `NutrientComponent` rows and
   `derived_amount(nutrient, amounts)`.
   - Done after re-examining it against the data: every formula was checked
     against the totals CIQUAL 2025 publishes. Four derivations are kept:
     vitamin A = retinol + beta-carotene / 12 (not / 6: 953 of 960 foods agree,
     against 346), folates in dietary equivalents = intrinsic folates + 1.7 x
     folic acid (631 of the 634 foods with a non-zero value agree to CIQUAL's
     rounding), salt = sodium x 2.5 (81 % of 2,437 within 5 %), and vitamin K = K1 + K2 (a
     nutrient CIQUAL does not have, created by the derivations). Vitamin D as
     D2 + D3 is not kept: CIQUAL's own total does not follow it.
   - On CIQUAL alone they fill few gaps (salt 10 foods, vitamin A 4, vitamin K
     81, folates 0, of 2,983): they matter for sources that give parts and not
     totals. The terms are in `services/derived_nutrients.py`, set up by the
     CIQUAL import (the nutrients they name only exist once it has run), and
     a factor must be positive.
   - `derived_amount` returns None when a component is missing, never a sum
     that counts it as zero. `complete_with_derived` adds the derived amounts
     a source lacks and never replaces one it gave.
   - **Vitamin A on labels (checked 2026-10-04).** Regulation (EU) 1169/2011,
     Annex XIII, gives vitamin A in µg (reference value 800) without defining
     the retinol equivalent or any conversion: the law does not say which
     convention a declared value follows. The EU scientific convention counts
     beta-carotene for a sixth (from summaries of EFSA's opinion on vitamin A;
     EFSA's page could not be opened), and CIQUAL's data for a twelfth (its
     documentation PDF has no text, so its own wording could not be read).
     Decision for step 8: choose neither. Compare a declared vitamin A with an
     interval whose ends count the carotene for a twelfth and for a sixth (a
     second derived nutrient, `vitamin_a_sixth`, built in step 8), which is the
     uncertainty the convention leaves. It only matters for foods whose vitamin
     A comes from carotene: added retinol is not affected.
   - What follows is the plan as written.
   - Vitamin A (RE) = retinol x 1 + beta-carotene x 1/6, both in µg.
   - Vitamin K = K1 + K2.
   - Review the CIQUAL list for others, for example niacin equivalents and
     vitamin E.
   - Service: `derived_amount(nutrient, amounts)`. A derived value is
     incomplete, not zero, when a component is missing.
4. **Reference ingredient composition** (done):
   `reference_composition(ref) -> dict[code, Estimate]`.
   - **Foods added by hand (2026-10-04).** CIQUAL had nothing for three of the
     muesli's ingredients, so the user created a source "Manual" and three foods
     were added in it, each worked out from CIQUAL foods and said so in its name:
     soy flakes from 20901 (soybean, whole), wheat flakes from 9060 (durum
     wheat, whole, raw), and freeze-dried berries from the raw redcurrant,
     blackcurrant and raspberry (13019, 13007, 13015) taken to 4 % water by dry
     matter. They have the 8 nutrients of the label, grade D, and a range that is
     the source's own widened to at least 15 %. They live in the database, as
     the curated references do, and are not seeded by code.
   - Done as planned (decision 3 as recommended), with these details. Every
     figure is an interval. A measured amount is the range the source's own
     data gives (CIQUAL's minimum and maximum), or else its rounding read from
     its decimals as for a declared figure (9.3 is 9.25 to 9.35, 1100 is 1099.5
     to 1100.5), kept at or under 100 for a nutrient in grams. "Below the
     detection limit x" is 0 to x and counts as x / 2; "traces" is from 0 with no
     upper end; "not measured" is not in the composition. A nutrient a food
     lacks is derived for it first (step 3), amounts and both ends. Foods are
     then combined per nutrient by the mean weighted by grade (A 4, B 3, C 2,
     D 1, none 1), the interval holding all of theirs; with one food it is that
     food's own, which was checked on the 536 measured values of the single-food
     references of the muesli against the XML. The reference's page shows it.
     Code: `services/reference_composition.py`.
   - What follows is the plan as written.
   - `Estimate` holds amount, low, high, qualifier, grades and source foods.
   - Aggregation follows decision 3.
   - Admin: show the aggregated composition read-only on
     `ReferenceIngredient`.
5. **Curating the references** (done, in the admin).
   - Done as planned, with these differences. The worklist is the list of
     references, most used first, with the number of ingredients using each
     and of source foods it draws on, filtered by status and by having source
     foods. A reference's page also suggests the imported foods that may fit
     its names (every word of a name in the food's name, the plainest first);
     linking one is still done in the "source foods" field, which finds foods
     by code or name. An action marks references as curated (those without an
     English name wait), and an action on foods creates one reference from
     the selection and opens it to be named. Code: `suggest_source_foods` and
     `create_reference_from_foods` in `services/reference_services.py`, and
     `admin.py`.
   - **Proposals to validate** (added 2026-10-04). An action on the list,
     "Propose CIQUAL foods", shows for each selected reference without foods
     the foods that may be what it is, why, and how sure it is, and links
     only what is ticked, each to the food chosen (those where the two
     signals agree are ticked already; an option marks the linked references
     as curated). Two signals that do not depend on each other are crossed:
     the name (CIQUAL names the thing first, "Cassis, cru"; a cooked or
     prepared food ranks lower unless the reference is cooked; names are
     compared within one language, since "raisin" is a grape in French and a
     dried one in English) and the CIQUAL code OpenFoodFacts' taxonomy gives
     (kept in `IngredientTaxon`, never trusted alone: 9311 for oat flakes is
     not in CIQUAL 2025). High confidence is both agreeing on a plain food,
     medium is the name alone with one plain match, low is anything else.
     Replayed on the four links made by hand on the muesli, the top proposal
     was the same four times. Code: `services/reference_proposals.py`.
   - What follows is the plan as written.
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
6. **Percentage estimation** (done): `estimate_percentages(product)`.
   - Done as planned (decisions 4 and 5), with these details and differences.
     The code is `services/percentage_estimation.py`, and its description says
     the rules. The unknowns are the share of the whole product of every
     ingredient, sub-ingredients included. The rules are: the ingredients at the
     top add up to 100 (only when one of them is undeclared, since a label that
     declares all of them need not add up: 99.4 is rounding); the
     sub-ingredients add up to their parent; a declared percentage holds within
     its rounding, and a sub-ingredient's is a share of its parent; the list is
     in non-increasing order (Regulation 1169/2011, article 18); and, for each
     of fat, saturated fat, carbohydrates, sugars, fibre, proteins and salt of
     the label, the lowest the compositions can make is under the label's upper
     end and the highest is over its lower end. The compositions are intervals,
     taken nutrient by nutrient, which keeps every rule linear: the intervals
     that result can be wider than the truth, never narrower. Energy is not a
     rule (a label computes it from the others), step 8 checks it. A food that
     lacks a nutrient has it from nothing to the one it is part of (sugars are
     carbohydrates), or to 100 g; one that lacks fat, carbohydrates or proteins
     has no composition.
   - Each percentage's lowest and highest values are two linear programs (HiGHS
     through scipy), and each `Interval(low, point, high)` is rounded outwards to
     0.01. The point is a combination in the middle of those that follow the
     rules, which follows them too, and a declared percentage keeps its own
     figure when it still holds. It is the mean, over 32 directions chosen once
     at random (always the same seed), of the middle of the combination most and
     the one least in that direction. The extremes of each percentage alone were
     tried first and leaned towards the corners where several combinations are
     as extreme (three sub-ingredients of 1.4 % in order came out 1.30, 0.06 and
     0.03; they now come out 0.91, 0.34 and 0.18, close to the 0.86, 0.39 and
     0.16 a uniform draw gives). **Difference from decision 4:** the point does
     not "best fit the declared nutrition". On the muesli a fit to the label's
     figures moved the declared soy and dates to the edge of their margin (31.5
     and 7.5) and put wheat and oats level, because the compositions are only as
     good as their intervals (the manual foods are known to 15 %).
   - **Difference from decision 5:** a sub-ingredient's percentage is always a
     share of its parent. The exception (a parent with no percentage and a
     value above every root's) was left out: it is ambiguous, and a reading that
     cannot hold already gives the "contradict each other" warning.
   - When the rules cannot all hold, nothing is guessed, and a warning says
     why: no composition for an ingredient (named) leaves the nutrition unused;
     a product with no declared nutrient too; a label the compositions cannot
     give (the nutrients that are off are named) leaves it unused, and says
     nothing of whether the label or the composition is wrong; declared
     percentages and order that contradict each other give no estimate.
     `used_nutrition` tells whether the label narrowed the result.
   - On the muesli (the three missing foods added by hand in the source
     "Manual", see step 4), with the label's order: wheat flakes 28.77-31.50
     %, oat flakes 24.43-29.91 %, raisins 1.35-3.54 %, buckwheat 0-1.45 %. Without
     the order they are far wider, and with the compositions as points rather
     than intervals no combination fits the label.
   - What follows is the plan as written.
   - Follows decisions 4 and 5.
   - Returns min, point and max per ingredient, plus warnings, for example
     declared percentages that are impossible.
   - Test against the muesli and hand-made trees: all declared, none
     declared, nested.
7. **Nutrient computation** (done): `estimate_nutrients(product)`.
   - Done as planned, with these details. Code: `services/nutrient_estimation.py`
     (and `Solution`, `solve_shares` in `percentage_estimation.py`, which both
     steps share). A nutrient's amount is its point, and its lowest and highest
     values are linear programs over the same combinations as the percentages
     (the label's nutrition included when it was used): the lowest content of
     each ingredient, minimised over them, and the highest, maximised. That is
     tighter than multiplying the ends of the percentages, which are bound to
     each other (they add up). The point is the middle combination of step 6
     with each ingredient's own amount, so it lies within its interval.
   - Coverage per nutrient is the share of the 100 g, as an interval, whose
     ingredients give a value. A nutrient missing from an ingredient is not zero:
     the amount and the lowest figure count it as nothing (what is at least
     there), and the highest figure is `None` unless the ingredient gives the
     nutrient it is part of (no sugars, but carbohydrates: at most those). A
     value of "traces" has no upper end either. An ingredient counts only if it
     has fat, carbohydrates and proteins, as in step 6.
   - On the muesli the label's nutrients are all given an interval that holds
     the declared figure (energy 1416-1739 kJ for a declared 1532, protein
     17.3-24.0 g for 21, sugars 8.0-12.2 g for 10, salt 0.012-0.021 g for 0.02),
     as wide as the manual foods' 15 %. Its vitamins are covered for 36-38 % of
     the product only, since soy flakes, wheat flakes and the berries have the
     nutrition of a label and nothing else: they have to be completed to say
     more. It takes 0.7 s on demand.
   - What follows is the plan as written.
   - Uses the **coarsest** level of each branch that has a composition, never a
     parent and its children together (changed on 2026-10-04 from "the finest",
     which step 6 already follows). A sub-ingredient is linked to the food as it
     is sold, and a parent describes what it became: "raisins secs (raisins,
     huile)" is dried grapes, 16 % water, while the fresh grape it is made of is
     82 %, and the freeze-dried berries are the same story. The finest level
     would count them for a quarter of their sugars. The sub-ingredients are used
     when the parent has no composition.
   - Amount = sum of percentage x composition / 100, with ranges carried
     from the percentage and source ranges.
   - Coverage is computed per nutrient, because CIQUAL has holes.
8. **Validation and confidence** (done): `validate_estimate(product)`.
   - Done as planned (decision 7 as recommended), with these details and
     differences. The code is `services/estimate_validation.py`, and its
     description says the rules. Every nutrient the product declares (the 8 of
     the label, and any other an admin entered) is set against the estimate as
     two intervals: the declared figure with its rounding, and the lowest and
     highest ends of the estimate. They agree when they meet. Otherwise the label
     is `declared_below` (it declares less than the ingredients bring at the
     least) or `declared_above`, with the gap in the nutrient's unit, and a
     non-blocking warning (`Problem.DECLARED_BELOW`, `DECLARED_ABOVE`) names the
     nutrient and both figures. A nutrient no ingredient gives is
     `not_estimated`. `validate_estimate` returns the nutrients and percentages
     of steps 6 and 7 with the checks, the confidence of each nutrient and all
     the warnings (the shares' first), in one pass: loading and solving once.
   - **The label is also an input.** The seven nutrients that step 6 takes as
     rules agree with the estimate by construction when they were used, so
     comparing them confirms nothing. A check marks them `constrained`, and they
     count for nothing in the confidence. What tests them is whether the shares
     could be worked out with them at all, which is step 6's `LABEL_DISAGREES`
     (its warning now carries the nutrients' codes as well as their names). The
     independent checks are energy, which a label computes from the others, and
     any nutrient outside the seven. On the muesli the declared 1532 kJ is within
     the 1416-1739 kJ the ingredients give, and nothing is flagged.
   - A nutrient given by only some of the ingredients has no highest end, so the
     label can only be found below it. Such a check cannot confirm much and does
     not count as an agreement either.
   - **Vitamin A** (decided in step 3): `vitamin_a_sixth`, retinol +
     beta-carotene / 6, is a second derived nutrient, created by
     `ensure_derivations` like vitamin K (`import_ciqual` runs it; the dev database
     got it from a direct call). `CONVENTIONS` maps `vitamin_a` to it, and a
     declared vitamin A is compared with the span of both readings, from the lower
     of the two lowest ends to the higher of the two highest, or open at the top if
     either is. A figure between the two readings agrees too: another convention
     would land there. Nothing declares a vitamin yet outside the admin (the form
     and the OFF import only know the 8 of the label), so this is tested but not
     seen on a real product.
   - **Confidence**, for each estimated nutrient: four parts between 0 and 1 and
     a score that is their product, worked out from the parts as shown. _Coverage_
     is the share of the product whose ingredients give the nutrient. _Quality_ is
     their foods' grades on the scale of the aggregation (A 1, B 0.75, C 0.5, D
     0.25, none 0.25), averaged for an ingredient with several foods and weighted
     by the shares. _Uncertainty_ is half the sum of the widths of the shares of
     the ingredients that carry the composition (what one gains, another loses),
     and counts against the score. _Agreement_ is the share of the informative
     independent checks that agree, a nutrient named by `LABEL_DISAGREES` counting
     as failed, and none when there is no such check (the score then takes 1:
     nothing contradicts the estimate, which is not that it was confirmed).
     Coverage and quality are the nutrient's, uncertainty and agreement the
     product's. The formula is a recommendation nobody has contested, and its
     figures (the grade scale, the product) are one place in the code to change.
   - On the muesli (0.7 s): uncertainty 0.07, agreement 1.00, coverage 1.00 for
     the macronutrients and 0.36-0.37 for the vitamins and minerals looked at.
     Proteins score 0.46 (quality 0.50: the three Manual foods, grade D, are 63 %
     of the product), vitamin C 0.26, vitamin A 0.23 and 0.15 counting the
     carotene for a sixth (quality 0.70 and 0.45), iron 0.32.
   - **Energy is graded D by CIQUAL for 2,842 of its 2,843 foods** (it is a
     computed value, and the source says so in its grades), so the quality of the
     energy of any product is 0.25 and its score at most 0.25, whatever the
     macronutrients it comes from. That is the source's grade, taken as given.
     Open: energy could take the quality of the nutrients it is computed from.
   - Not modelled, as in step 6: a declared zero has no margin (a label's "0 g"
     can stand for under 0.5 g, so a food with a little of the nutrient flags it),
     and the tolerances the EU allows between a label and the food are not
     added to the rounding.
   - What follows is the plan as written.
   - Compare the computed and declared values for the 8 label nutrients.
     Report the gaps, then build the confidence object of decision 7. Warnings
     stay non-blocking.
9. **Output** (done): `GET /api/v1/products/{barcode}/estimate`, read-only, for
   signed-in users.
   - Done as planned, with these details and differences. One builder,
     `build_estimate(product)` in `services/estimate_report.py`, makes the
     `EstimateOut` schema (in `api/schemas/outbound.py`) that the endpoint
     returns and the page renders, so the presentation is written once. The
     endpoint is authenticated like the rest of the API (session or the mobile
     app's token) and refuses anything but GET.
   - **Difference from the plan:** `estimated` is not always present for an
     ingredient: it is `null` when the label contradicts itself and nothing could
     be estimated (the warning `impossible` says so). A declared ingredient does
     get its declared interval narrowed by the rest, as planned.
   - Per nutrient, in catalogue order: `estimated` (low, point, high, the high
     `null` when no upper end is known), `coverage`, `confidence` (score and its
     four parts), `declared` (the label's figure with its rounding) and `check`
     (verdict, gap, whether it was `constrained`, and the interval compared). The
     nutrients the label declares are listed even when no ingredient gives them.
     Vitamin A is one entry with its second reading in `other_readings`:
     `vitamin_a_sixth` is not an entry of its own.
   - The response also carries the warnings (problem, message in the language
     served, nutrients), the `sources` the figures draw on with their attribution,
     and the `caveat` that processing is not modelled (see Out of scope).
   - **The page**: a card under the form on the product's edit page, in its own
     full-width row (the form's column is too narrow for a table of this many
     columns: in it the card was 13,000 px tall). Two tables, the ingredients with
     the label's percentage and the estimated one apart and muted, and the
     nutrients with the label, the estimate, its range, coverage, confidence
     (the score, then its four parts on one line, with a legend) and the check. It
     is worked out on each GET of the page (about a second for the muesli) and not
     after a failed POST. A solver failure (`RuntimeError`) is logged and the page
     says the estimate could not be worked out: the form must not break on it.
     Figures are shown to three significant digits (`templatetags/estimate_tags.py`)
     and the label's as it was written. No chart: it was proposed and not decided.
   - **CIQUAL attribution** is shown where its data appears: in the response, on
     the page, and under the composition of a reference in the admin (which had
     none).
   - Checked in Chromium on the muesli, in English and in French: no console error,
     no failed request, no horizontal overflow, 83 rows (14 ingredients, 69
     nutrients).
   - What follows is the plan as written.
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
    translations (`.po`). The entries of steps 8 and 9 are translated already
    (22, inserted without regenerating the catalogue). Left: `save`, untranslated
    before, and the fuzzy `Other`, whose translation is the one of `Others`.

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
