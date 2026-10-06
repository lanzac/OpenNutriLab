# Plan: preparations next to reference ingredients

Status: all five steps done (2026-10-06). Written 2026-10-05,
after the nutrient estimation batch, `docs/plans/lot-estimation.md`.

## Why

A label lists "mozzarella" as an ingredient, and `ReferenceIngredient` was made
for the ingredients of a product. But a mozzarella is itself a product, made of
milk, salt and rennet, and the label of the muesli-like gnocchi says so
(`mozzarella 6 % [lait, sel, présure microbienne, ...]`). It is not an ingredient
to be curated and linked to a food as if it were milk or salt. The user's rule
(2026-10-05): **`ReferenceIngredient` holds true ingredients only**, and what is a
product or a preparation has to be told apart.

In the development database 8 of 35 references are in that position, and which
ones are _preparations_ is a human judgement, not something the text shows: raisins
secs (raisins, huile) and dattes (dattes, farine de riz) list parts too, and the
user keeps them as ingredients.

## Ground rules (decided by the user, 2026-10-05)

- A preparation is **made of several ingredients**. Mozzarella, gnocchi, "préparation
  d'oignon", a sauce, a pastry are preparations. A food that is transformed but is
  one material stays an ingredient: raisins secs, dattes, purée de tomate, oignon
  grillé, huile d'olive, fruits rouges lyophilisés.
- A `Preparation` has its names and a status, and **points to the true ingredients
  it is made of**. It is an intermediate table between what a label says and the
  references.
- When the label lists the parts of a preparation (the mozzarella of this product),
  **the label's parts are kept**. When it does not, **the preparation gives its
  default references**.
- When the label lists no parts, the composition of a preparation comes from a
  **source food** (CIQUAL's "Mozzarella") when it has one, as a reference does.
- The label stays the reference for everything it says: nothing here changes what
  is read from the text.

## Decisions taken in this plan, to confirm

Each one has a recommendation. They were not put to the user one by one.

1. **Model.** `Preparation`: `name_fr`, `name_en` (each unique when filled, a
   curated one needs its English name, as for references), `status` (to review,
   curated), `description`, `components` (many references: what it is made of, with
   no proportions) and `source_foods` (many source foods: its measured composition,
   if any). `Ingredient` gets a nullable `preparation` next to its `reference`,
   which becomes nullable, with a check that exactly one is set, and the uniqueness
   constraints written for both. Both stay `PROTECT`.
2. **A name is a reference or a preparation, never both.** The database cannot say
   it across two tables, so the services and the admin refuse a name the other
   table has, and the lookup of a label's name looks in both.
3. **No automatic classification.** Nothing guesses what is a preparation: the
   text does not say it (see above). A name that matches nothing still creates a
   reference _to review_, as today. The admin helps the human: the list of
   references shows how many times each was seen with parts on a label, and an
   action **"Make a preparation"** converts the selected references: names and
   status move to a new preparation, the foods it drew on become its source foods,
   the references it was seen made of on labels (its parts, distinct) become its
   components to review, every ingredient that used it is repointed, and the
   reference is deleted. Nothing is lost, and the conversion can be done on the
   mozzarella, the gnocchi and the "préparation d'oignon" of the development
   database as soon as the action exists.
4. **Composition of a preparation** (the rule of the estimation, step 7 of its plan:
   the coarsest level that has one counts, in a branch). In that order:
   1. its source foods, aggregated as a reference's are (decision 3 of the
      estimation plan): it is what the preparation became, so it counts even when
      the label lists its parts;
   2. else the parts the label lists, as now (each a reference or a preparation);
   3. else its default references: as their shares are not known, each nutrient is
      somewhere between the lowest and the highest of its components', and the
      amount is their mean. That is the widest honest reading (any mix lies in it),
      with no grade, so it weighs little in the confidence. It is not a fit: it
      says "made of these" and no more;
   4. else no composition, and the warning of the estimation says so, as now.
5. **The API and the page** show an ingredient as either a reference or a
   preparation: `IngredientOut` and the estimate keep `reference` (now `null` for a
   preparation) and gain `preparation` (id, name, status). The ingredients table of
   the form says which it is next to the status.

## Steps (one commit or more each, tests with each)

1. **Preparation and the link** (done): migration 0011, model, admin. The model, the
   nullable pair on `Ingredient` with its constraints, the cross-table uniqueness of
   names, the admin with its usages count, components and source foods, and "mark as
   curated". Existing ingredients are unchanged (all references).
   - Done as planned, with these differences. What a reference and a preparation
     share (names, notes, status, the `name` property) is an abstract base,
     `CuratedItem`, which changes nothing in the reference's columns. A name clash
     is told per language (a reference's French name against a preparation's French
     name), since "raisin" is two things in French and English, and by two
     complete messages so that each translates. `Ingredient.item` gives the one it
     is.
   - What step 2 was to read is read already, so that nothing breaks while the
     link is nullable: the loader of the estimation, the rows of the page, the
     API (`reference` and `preparation`, one of them null), the estimate report
     and the ingredient admin. A preparation that draws on source foods already
     counts by them (decision 4.1): `reference_composition` takes either. Left
     for step 4: its default references.
   - **Found on the way, and fixed**: the pages of an ingredient in the admin gave
     a 500 since the curation tools of the estimation batch. The ordering "most
     used first" of the references' admin used an annotation that Django does not
     have when it applies the same ordering to the field of another admin that
     points to them. It is a subquery now (`most_used_first`), so it works with and
     without the annotation, and the preparations' admin uses it too.
2. **Writing ingredients** (done). `find_references` / `resolve_references` /
   `existing_references` look in both tables (a name a preparation has finds it,
   in either language, in the plural, or through the English correspondence; a
   name that matches nothing still creates a reference to review);
   `_replace_ingredients` writes either; the page's drafts from OpenFoodFacts
   show either. A tree can mix both. (Reading either was done in step 1.)
   - Done as planned, with these differences. The lookup takes one query for each
     table, so two where it took one (the number does not depend on the names).
     What the services return is `Item`, an alias of the two kinds. A name in a
     language is still read before the same word in the other, across the two
     tables: a reference's French "pasta" and a preparation's English "pasta" are
     not a clash, and the language asked wins.
   - Not in the plan, and done because decision 2 asks the services to refuse a
     name the other table has: `create_reference_from_foods` (the admin's "create
     a reference from these foods") refuses a name a preparation has.
   - The page's rows prefetch the foods of references and of preparations
     separately, since the two tables can share an id.
   - What is not done here, on purpose: nothing makes a preparation from a label
     (decision 3), and a preparation's default references are not written as
     children when the label lists no parts: they are read when it is estimated
     (step 4).
3. **"Make a preparation"** (done) on the references' admin, with the count of times
   seen with parts, and its tests (usages repointed, names and foods moved,
   components from the parts seen, nothing left behind, a name in use refused).
   - Done as planned, with these differences. The conversion is a service,
     `preparation_services.convert_to_preparation`, that the admin calls, so it
     can be used elsewhere. The action has two steps, like the proposals of
     foods: a page says what each reference becomes (its components, the foods
     it brings, what is refused and why), and nothing is deleted before the
     second one ("apply"). It needs the permissions of what it does: add a
     preparation, change ingredients, delete references.
   - The status moves as it is, as the plan says: a curated reference gives a
     curated preparation. Its components are marked in the description ("to
     check") when they come from the labels, since the status does not say it.
   - Two refusals, both leaving everything as it was: a name a preparation
     already has (the same word in the other language is not one), and a
     reference that is a component of a preparation (a preparation is made of
     references, and taking it out there would lose what that one is made of).
     The others of a selection are converted anyway, and the curator is told for
     each that is not.
   - The components are the references the label listed under it, once each. A
     part that is a preparation is not taken: a preparation is made of references
     only, and its own parts are its own.
   - The label's parts are never touched: they stay the children of the ingredient,
     which is repointed in place (same row, same percentage).
   - On the development database, a dry run (rolled back) of the three that are
     preparations, then the curator's own conversion in the admin, gave the same:
     mozzarella (components: milk, salt, microbial rennet, and "Acid", which comes
     from the additive heading "acidifiant : acide citrique" read as an
     ingredient, see "Out of scope"), gnocchi, préparation d'oignon.
4. **Estimation** (done). What was left of decision 4: the default references of a
   preparation that has no source food and whose label lists no parts (the hull of
   their compositions), and the sources of those references credited in the
   report. The rest (source foods, the label's parts, no composition) worked from
   step 1.
   - `reference_composition.components_composition` is the hull: a nutrient is
     somewhere from the lowest to the highest of its components', the amount is
     the mean of theirs, and it has no grade, so its quality in the confidence is
     the lowest (a quarter). `percentage_estimation.load` uses it for an
     ingredient that is a preparation with no source food and no part listed
     _under that ingredient_: the same preparation can be counted by its parts in
     one place of a product and by its components in another.
   - **Decision taken, to confirm: all or nothing.** A component with no
     composition gives the preparation none, and a nutrient one component does not
     give is left out of it. The shares are not known, so a component with nothing
     could be most of the preparation (the dehydrated potato of the gnocchi is),
     and a nutrient missing from a food is not zero. The warning of the estimation
     then names the preparation, as for any ingredient with no composition. The
     curator's way out is to link foods to that component or to take it out of the
     components. The cost is that a minor component without composition (rennet,
     ferments, an additive) blocks the hull until the additives are apart (see
     "After the batch").
   - The report credits the sources of the components of the preparations that
     count by them. It credits them also when one component had none and the hull
     was left empty, which is more than was used and never less.
   - Nothing changes on the development database: its three preparations have the
     parts their label lists, which count.
5. **Docs and translations** (done): the roadmap, this plan. The `.po` got the
   entries of step 3 with it, and step 4 has no text for a reader to translate: the
   French catalogue has no message untranslated or fuzzy.

## Out of scope

- Proportions of a default recipe (a mozzarella is 70 % milk...): the components have
  none, and the composition comes from a source food when one is wanted precise.
- Treating a preparation's default references as parts in the shares of the
  estimation (sum to the parent): the hull of their compositions is as wide and
  much simpler, and a recipe with proportions is where that would come back.
- Function words that head a list of additives are not ingredients either:
  "acidifiant : acide citrique" is read as an ingredient `acidifiant` with `acide
citrique` in it, and `acidifiant` ends up a reference to review. The classes
  (acidifiant, émulsifiant, colorant, conservateur...) are a closed list, so
  reading them as headings only is a rule of the label parser and not a guess. It
  belongs to the additives lot, below.

## After the batch

What the user decided on 2026-10-06, after steps 1 to 3, and what stays open.

- **A transformed food that is one material stays a reference**: tomate cerise
  mi-séchée, pomme de terre déshydratée, oignon grillé, huile d'olive vierge extra.
  No table for the transformation, and no "base food and state" with a fallback to
  the raw food, since a dried food is several times more concentrated than the raw
  one and the estimate would be wrong without saying so. What changes the nutrients
  is the food the reference is linked to, and CIQUAL names the state ("Huile
  d'olive vierge extra", "Flocons de pomme de terre, nature, déshydratés", "Tomate,
  séchée", "Oignon, cuit"). Several foods on one reference give an interval that
  holds them all, which says honestly that "mi-séchée" is between the raw and the
  dried. What the label does not say (how grilled) is not modelled.
- **Additives get their own table, in a lot of their own** (not planned in detail
  yet). Their lists are closed (E numbers, functional classes) and OpenFoodFacts
  separates them too. CIQUAL has almost nothing for them (among the imported foods:
  gelatine, sodium bicarbonate, dried agar, baking powder, soy lecithin), so as
  references each would stay "to review, no composition" for good, and add a
  warning and lower the confidence for a share of about 1 %. It also settles the
  heading question above: the class is a property of the additive. A third nullable
  link on `Ingredient`, exactly one of three, as in step 1; at a fourth kind, a
  single link would be worth it. Some additives are vitamins or minerals (E300
  ascorbic acid, E101 riboflavin, E160a carotenes, E306 to E309 tocopherols, E170
  calcium carbonate), so an additive must be able to say which nutrient it brings
  and how much per 100 g (from its specification and its formula, not from a food
  table), source foods being the second way. Whether flavourings, ferments and
  rennet go in the same table is left for that lot: for now they stay references.
- **A proposal of the English name** of a reference that has none (6 of the 32
  references in the development database), for the curator to accept. It is
  computed and shown, never written in `name_en`: that is a key by which labels
  are looked up, and "mark as curated" accepts whatever has one.
- **The composition of a preparation in its admin page**, as a reference's page
  shows it (its foods' values, or the range of its components').
- **Components with no composition** (see step 4) may need a softer rule once
  additives and minor ingredients are apart.
