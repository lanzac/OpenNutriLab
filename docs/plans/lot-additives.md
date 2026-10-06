# Plan: additives, apart from the reference ingredients

Status: steps 1 and 2 done (2026-10-06), the rest planned. Written 2026-10-06, after the preparations,
`docs/plans/lot-preparations.md`, from what the user decided that day.

## Why

A label lists additives with the ingredients: "acidifiant : acide citrique", "E330",
"colorant : caramel ordinaire". They are not ingredients in the sense the rest of
the model gives the word, and as references they cause three problems:

- **They have no composition to find.** Among the CIQUAL foods imported, the
  nearest are gelatine, sodium bicarbonate, dried agar, baking powder and soy
  lecithin. There is nothing for pectin, gums, colourings, acids, phosphates,
  sorbates or nitrites. So each additive reference stays "to review, no
  composition" for good, which adds a warning to the estimate and lowers its
  confidence for a share of the product that is about 1 %.
- **The label parser reads their class as an ingredient.** The development
  database has `Acid` / `Acidifiant` as a reference, with `acide citrique` under it,
  and it ended up as a component of the mozzarella. The classes are a closed list,
  so reading them as headings is a rule of the parser, not a guess.
- **Some of them are vitamins or minerals**, which is the subject of the whole
  project: E300 ascorbic acid is vitamin C, E101 is riboflavin (B2), E160a are
  carotenes (provitamin A), E306 to E309 are tocopherols (vitamin E), E170 is
  calcium carbonate. A table of additives has to be able to say so.

## Ground rules (decided by the user, 2026-10-06)

- **Additives have a table of their own**, in a lot of their own, apart from the
  references and the preparations. Their lists are closed (E numbers, functional
  classes) and OpenFoodFacts keeps them apart too.
- **Flavourings, ferments and rennet stay references for now.** They share the
  problem (small, no composition), and the question of a common table is left
  until this lot is done.
- **An additive that is a vitamin or a mineral is linked to the nutrient it brings**,
  with an amount per 100 g. The user never said that an additive counts for zero,
  and nothing here assumes it (see decision 4).
- A transformed food that is one material (dried, grilled, extra virgin) is not an
  additive and stays a reference, whatever the plan of the preparations said of it.

## What the data says

- The imported OpenFoodFacts taxonomy has 712 entries that are E numbers
  (`en:e330`, `en:e1001ii`...). In 706 of them both names are the bare code, and
  6 have a French name for the substance: it gives the code, almost never the
  substance's name, and never its class. So it is a list of codes to start from,
  and the names and classes are for the curator or another source.
- The label of the development product reads `mozzarella 6 % [lait, sel, présure
microbienne, acidifiant : acide citrique]`. The two ways a label writes an
  additive are the name ("acide citrique") with or without its class heading, and
  the code ("E330"), alone or after the name ("acide citrique (E330)").

## Decisions taken in this plan, to confirm

Each has a recommendation. They were not put to the user one by one.

1. **Model.** `Additive`, on the same base as the other two (`CuratedItem`: names,
   notes, status), with `code` (the E number, such as "E330", unique when
   filled, blank for an additive that has none), `function` (its functional
   class, from the closed list, blank when unknown) and the nutrients it brings,
   `AdditiveNutrient` (additive, nutrient, amount per 100 g, a note on where the
   figure comes from). It may also draw on source foods, as the others do, for the
   few that a table has. `Ingredient` gets a third nullable link, `additive`, with
   the check "exactly one of the three" and the uniqueness constraints written for
   all three, as step 1 of the preparations did for two. At a fourth kind, one
   link to a single table would be worth it. A name is one kind only, as for the
   other two: the services and the admin refuse a name another table has.
2. **How an additive is told from a label.** By the text only, as everything else:
   - a word that is an E number (`E330`, `E 330`, `e330`) is an additive, and
     is found by its code first;
   - a name that an additive has is found as the references and preparations are;
   - any other name is looked up as now, and a name that matches nothing still
     creates a reference to review, never an additive: the text does not say that
     "xanthane" is one (the curator converts it, as for a preparation).
     An E number that matches no additive creates one, to review.
3. **The label parser** (`label_parser.py`) reads the functional classes
   (acidifiant, émulsifiant, colorant, conservateur, épaississant, antioxydant,
   gélifiant, exhausteur de goût, stabilisant...) as headings, in French and in
   English, when they stand before a colon or a parenthesis and a list. The heading
   is not an ingredient: it becomes the function of the additives under it, and the
   additives are listed as the ingredients they are (the parent's parts). A text
   the parser cannot read is still reported and the reading stops, with no repair.
4. **The estimate.** An additive has the composition its nutrients give. One with
   none is **unknown, as any ingredient with none is**, which is a warning and a
   lower confidence: that is the honest default. The curator can say of an
   additive that it brings nothing of the nutrients (citric acid and the vitamins,
   say) with a flag and a note, which counts for zero _by that claim_, per
   additive, written down, and not by default. Its share stays an interval
   bounded by the label's rules, so what it can weigh is shown. The alternative is
   to count every additive with no figure as zero, which is simpler and wrong for
   caramel or a sweetener.
5. **Where the figures of a nutritive additive come from.** Not from a food table:
   from the additive's specification (the purity the regulation asks for) and its
   formula (calcium carbonate is about 40 % calcium). The curator enters them with
   a note on where they come from. **To verify before relying on it**: that the
   European specifications give that purity for each additive, which was not
   checked. Nothing is imported automatically in this lot.
6. **Converting a reference into an additive**, as for a preparation: an action on
   the references' admin, in two steps, that moves the names and notes, the foods,
   repoints the ingredients and deletes the reference. A class that was read as an
   ingredient (`Acidifiant`) is not converted: it is deleted once the parser has
   been fixed and the label read again.

## Steps (one commit or more each, tests with each)

1. **Additive and the link** (done): migration 0012, model, the third nullable link
   and its constraints, the cross-table names, the admin (code, function,
   nutrients, usages count), and the readers that take an ingredient of any kind
   (page, API, estimate, ingredient admin).
   - Done as planned, with these differences. The functional classes are the 26 of
     the European additives regulation, as choices, with their French labels
     (the words a label uses are for step 3). The code is written the one way ("e
     330" is "E330") by the form's validation, and is unique whatever its case.
     The help text of the nutrients' note had to lose its "40 %" (a percent sign in
     a text to translate reads as a format). The check on `Ingredient` is "exactly
     one of the three", and its old message left the catalogue for the new one.
   - The test settings now set `TRANSLATION_URL` to nothing: a test of the English
     names had come to depend on the machine's environment, which the local
     Compose file now fills.
   - The user's development database was migrated (0012): without it the running
     site would have failed on the new column.
2. **Writing ingredients** (done): the lookups in three tables, E numbers by their
   code, `_replace_ingredients`, the drafts on the page.
   - An E number is read by `e_number`: `E330`, `e330`, `E 330`, `E160a`,
     `E1001(ii)` and `E1001ii`, and not a word with other letters or fewer than
     three digits. It is found by its code before any name. One no additive has
     gets an additive to review whose English name is the code, and whose French
     name is the taxonomy's when that is more than the code (6 of its 712 E
     numbers). A name that is not an E number is looked up as before, and one
     that matches nothing is still a reference, never an additive.
   - A lookup now takes three queries, one for each table. The English-name
     proposal and the service that creates a reference from foods refuse a name
     an additive has too.
   - What stays for step 3: the label's text is not read differently yet, so
     "acide citrique (E330)" still reads `E330` as a part of `acide citrique`,
     and `acidifiant : acide citrique` still makes a reference `acidifiant`.
3. **The label parser** (`label_parser.py`) reads the functional classes
   (acidifiant, émulsifiant, colorant, conservateur, épaississant, antioxydant,
   gélifiant, exhausteur de goût, stabilisant...) as headings, in French and in
   English, when they stand before a colon or a parenthesis and a list. The heading
   is not an ingredient: it becomes the function of the additives under it, and the
   additives are listed as the ingredients they are (the parent's parts). A text
   the parser cannot read is still reported and the reading stops, with no repair.
4. **The estimate.** An additive has the composition its nutrients give. One with
   none is **unknown, as any ingredient with none is**, which is a warning and a
   lower confidence: that is the honest default. The curator can say of an
   additive that it brings nothing of the nutrients (citric acid and the vitamins,
   say) with a flag and a note, which counts for zero _by that claim_, per
   additive, written down, and not by default. Its share stays an interval
   bounded by the label's rules, so what it can weigh is shown. The alternative is
   to count every additive with no figure as zero, which is simpler and wrong for
   caramel or a sweetener.
5. **Where the figures of a nutritive additive come from.** Not from a food table:
   from the additive's specification (the purity the regulation asks for) and its
   formula (calcium carbonate is about 40 % calcium). The curator enters them with
   a note on where they come from. **To verify before relying on it**: that the
   European specifications give that purity for each additive, which was not
   checked. Nothing is imported automatically in this lot.
6. **Converting a reference into an additive**, as for a preparation: an action on
   the references' admin, in two steps, that moves the names and notes, the foods,
   repoints the ingredients and deletes the reference. A class that was read as an
   ingredient (`Acidifiant`) is not converted: it is deleted once the parser has
   been fixed and the label read again.

## Steps (one commit or more each, tests with each)

1. **Additive and the link**: migration, model, the third nullable link and its
   constraints, the cross-table names, the admin (code, function, nutrients, usages
   count), and the readers that take an ingredient of any kind (page, API,
   estimate, ingredient admin).
2. **Writing ingredients**: the lookups in three tables, E numbers by their code,
   `_replace_ingredients`, the drafts on the page.
3. **The label parser**: the classes as headings, the E numbers, and the tests of
   the forms above (`acidifiant : acide citrique`, `acide citrique (E330)`,
   `colorant : E150a`, a class with no list after it, a class written in English).
4. **"Make an additive"** on the references' admin.
5. **The estimate**: the nutrients of an additive, the flag "brings nothing" and what
   it does to the warnings, the confidence and the report's credit of sources.
6. **Docs and translations**: the roadmap, this plan, the `.po`.

## Out of scope

- Importing additive data (names, classes, specifications) from a database. The
  taxonomy gives codes only, and the other sources were not looked at.
- Risk or regulatory data on additives (EFSA evaluations, authorised uses).
- Flavourings, ferments and rennet, which stay references.
- Additives that are not on the label: carry-over, processing aids.
