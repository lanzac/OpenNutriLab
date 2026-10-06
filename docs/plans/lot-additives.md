# Plan: additives, apart from the reference ingredients

Status: steps 1 to 3 done (2026-10-06), the rest planned. Written 2026-10-06, after the preparations,
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
- OpenFoodFacts also publishes a taxonomy of additives
  (`static.openfoodfacts.org/data/taxonomies/additives.json`, next to the
  ingredients one). Measured on 2026-10-06: 764 entries, of which 729 have an E
  number (the 35 others are not additives: `en:no7`, `de:quellkohlensäure`, a bare
  class `en:colour`...), 711 have an English name and 654 a French one, written
  "E330 - Acide citrique". It has no synonyms ("Lécithines" is there, "lécithine de
  soja" is not), and its classes cannot be trusted: 374 entries have any, from 13
  classes of its own, E330 is "antioxidant, sequestrant" and not an acid, and
  E500ii is "stabiliser, thickener". It gives no composition. A few names are
  shared by two entries ("riboflavin" is E101 and E101i).
- Of the 32 references of the development database, one has the name of an additive
  of that list: `acide citrique`, which is E330. `Acidifiant` is a class, which the
  list has not.

## Decisions taken in this plan, to confirm

Each has a recommendation. They were not put to the user one by one, but 1 to 3
were told to the user before they were built.

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
   - an E number written next to a name ("acide citrique (E330)") is that
     additive's code;
   - a name under a functional class ("acidifiant : acide citrique") is an
     additive, since the class is what the text says it is for, and it carries the
     class;
   - a name that an additive has is found as the references and preparations are;
   - any other name is looked up as now, and a name that matches nothing still
     creates a reference to review, never an additive: the text does not say that
     "xanthane" is one. The curator converts it, or the list imported in step 5
     already knows it.
     An E number, or a name under a class, that matches nothing creates an
     additive, to review.
3. **The label parser** (`label_parser.py`) reads the functional classes
   (acidifiant, émulsifiant, colorant, conservateur, épaississant, antioxydant,
   gélifiant, exhausteur de goût, stabilisant...) as headings, in French, English
   and, for the commonest, Spanish, and not as ingredients. See step 3.
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
   checked. Nothing about figures is imported automatically in this lot.
6. **Converting a reference into an additive**, as for a preparation: an action on
   the references' admin, in two steps, that moves the names and notes, the foods,
   repoints the ingredients and deletes the reference. **When an additive already
   has the reference's name or code (which the import of step 5 makes the usual
   case), the ingredients are repointed to that additive and the reference is
   deleted, instead of an additive being made twice.** A filter shows the references
   that are known as additives, and the page of the action has them ticked when the
   match is exact. Nothing is converted without that second step: some names are
   foods too ("agar-agar", "caramel"). A class that was read as an ingredient
   (`Acidifiant`) is not converted: it is deleted once the parser has been fixed
   and the label read again.
7. **The list of additives** (step 5), to confirm: the entries of OpenFoodFacts'
   additives taxonomy that have an E number (729), with their code and their
   names, as additives **to review**, **with no class** (the taxonomy's are not
   reliable: the label's class, or the curator, gives it). An additive that
   exists already with the same code or the same name is completed with what it
   lacks (its code, the other language's name), never made twice and never
   overwritten. A name that a reference or a preparation has is kept on the
   additive all the same, and reported: that is the sign that the reference is to
   be merged (decision 6), and until it is, the reference is what a label finds. A
   name two entries share goes to the first, and the second keeps its code as
   its name. The data is OpenFoodFacts', under its licence, as the ingredients
   taxonomy already is.
8. **Existing products** keep their ingredients until their label is read again.
   A command reads again, from the text stored with each product and with no
   network, every product that has one, replacing its tree as saving does. One
   that has no stored text (the muesli) is read again from its page ("Reset data").
   To confirm: whether the command is wanted.

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
   - An E number is read by `e_number`: `E330`, `e330`, `E 330`, `E-150d`, `E160a`,
     `E1001(ii)` and `E1001ii`, and not a word with other letters or fewer than
     three digits. It is found by its code before any name. One no additive has
     gets an additive to review whose English name is the code, and whose French
     name is the taxonomy's when that is more than the code (6 of its 712 E
     numbers). A name that is not an E number is looked up as before, and one
     that matches nothing is a reference.
   - A lookup now takes three queries, one for each table. The English-name
     proposal and the service that creates a reference from foods refuse a name
     an additive has too.
3. **The label parser** (done): the classes as headings, the E numbers, and the
   tests of the forms (`acidifiant : acide citrique`, `acide citrique (E330)`,
   `colorant (E150a)`, a class with no list after it, a class written in English).
   - A class applies to the item that follows its colon, and to no other: the text
     does not say where the list ends. In parentheses it applies to every item,
     but only when they are E numbers or the class is not also what an ingredient
     is called ("amidon modifié (maïs)" is cornstarch, "poudre à lever" is an
     ingredient): those three classes (modified starch, raising agent, carrier)
     head a list in parentheses only when it is E numbers. A class with a
     percentage on it, or with nothing after it, is read as any word is. **This
     differs from what was planned**: a class with nothing after it does not stop
     the reading, since "poudre à lever" alone is a label's ingredient.
   - An E number next to a name is its code in either order ("acide citrique
     (E330)", "E330 (acide citrique)"); several codes, or one with parts, stay the
     parts they were. An E number at the top of a list is no name that is too
     short.
   - A name under a class that nothing has is made an additive, to review, with
     that class, and so is a name with an E number next to it. An additive found
     that has no class gets the one the label gives, and keeps its own if it has
     one. A reference that has the name stays what a label finds, whatever the
     class: the curator converts it.
   - `LabelItem` and `IngredientInput` carry `function` and `code`. The words are
     French, English and a few Spanish ones, a test keeps the 26 classes and their
     words together, and the label of the development gnocchi now reads
     `mozzarella [lait, sel, présure microbienne, acide citrique (acid)]` with no
     `acidifiant` ingredient.
4. **"Make an additive"** on the references' admin (decision 6): the conversion, its
   merge into an additive that has the name or the code, the filter of the
   references known as additives, and, if wanted, the command of decision 8.
5. **The list of additives** (decision 7): a command that imports the entries of
   the taxonomy that have an E number, as additives to review, like
   `import_off_taxonomy`; and the report of the references that have the name of
   one.
6. **The estimate**: the nutrients of an additive, the flag "brings nothing" and what
   it does to the warnings, the confidence and the report's credit of sources.
7. **Docs and translations**: the roadmap, this plan, the `.po`.

## Out of scope

- The nutrient figures of additives, from any database: the taxonomy has none, and
  the specifications that could give them were not looked at. They are entered by
  the curator, a dozen of them mattering (the vitamins and minerals).
- The official list of additives of the European Union as a source: not looked at,
  OpenFoodFacts' list being the one that was measured.
- Risk or regulatory data on additives (EFSA evaluations, authorised uses).
- Flavourings, ferments and rennet, which stay references.
- Additives that are not on the label: carry-over, processing aids.
