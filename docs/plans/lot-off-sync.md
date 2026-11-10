# Plan: compare with OpenFoodFacts, correct the list, send it back

Status: built 2026-11-02 (cb57434). Asked by the user on the product form: the
button "Récupérer les données" did not say where from; used on a form that was filled
in it **replaced** what was there with no way to say no; the ingredients could not be
corrected without first correcting them in the OpenFoodFacts app; and, if possible,
the corrections should go to OpenFoodFacts, for the admin only.

## What it does

- **One button, named for where the data comes from.** "Charger depuis
  OpenFoodFacts" on a new product, "Comparer avec OpenFoodFacts" on a saved one
  (`#off-lookup`). It asks OpenFoodFacts **without reloading the page**
  (`GET /products/lookup-off/?barcode=`, `OffLookupView`), so what was typed and not
  saved stays.
- **What it finds is set against the form, never poured over it**
  (`form/off-lookup.js`). A value the form has not got yet is filled in at once. When
  OpenFoodFacts has another value than one the form has, a panel lists the two side
  by side (fields, ingredient list, photo), each line ticked, and the person takes
  what they choose. Nothing in the form changes before "Prendre la sélection". A
  value OpenFoodFacts does not have is no proposal: it never empties a field.
- **The ingredient list is corrected in the form.** "Corriger le texte" turns the
  list into an editor; "Lire ce texte" reads it (the same `POST /products/read-label/`
  as the places left out) and the table follows. The corrected list is saved with the
  product like any other. A new product, or one with no stored list, gets an empty
  block to write the list in.
- **Staff can send the corrected list to OpenFoodFacts.** A button
  "Envoyer cette liste à OpenFoodFacts" appears for a list corrected on the page, only
  for staff, only when the site has an OpenFoodFacts account (`OFF_USER_ID`,
  `OFF_PASSWORD`). It asks to confirm, then `POST /products/send-label/`
  (`SendLabelView`, staff only, 404 without an account) writes
  `ingredients_text_<language>` through `cgi/product_jqm2.pl`.

## Decisions I took (not asked, say so if the user disagrees)

- **Correcting the text relaxes `feedback-label-text-only`** (a person could only take
  places out). The rule's reason stands: the label's words are still the only source
  and no code guesses what was meant; the person is the one who corrects. The places
  left out are emptied when the text is corrected or replaced (their positions belong
  to the old text).
- **A list is language-tagged** with the language of the lookup, else of the stored
  list, else of the page (`ingredientsText.defaultLanguage`), for a list typed where
  none was known. OpenFoodFacts is sent the list in that language.
- **Sending is guarded**: only a product OpenFoodFacts already has is edited (the
  write API would otherwise create one holding nothing but a list), nothing is sent
  when its list is already this one, an empty list or a language that is not a
  two-or-three letter code is refused, and the error shown never carries OpenFoodFacts'
  detail (it is logged). Each send is logged with the staff member's name.
- **Ticked by default**: every line, except the photo of a product that has one (an
  identical picture would be downloaded again). "Prendre la sélection" is always an
  explicit click when something would be replaced; with nothing to replace there is
  nothing to ask.
- **`?reset=1` on the edit page is gone** (it was the reload that replaced the form).
  `?barcode=` on the create page stays: the inventory's scan and "create the
  product" link to it.
- **A save writes the list only when the page carries one** (`off_ingredients` set),
  not whenever `off_barcode` matches: taking only the photo of a lookup no longer
  wipes the saved list.
- **The OpenFoodFacts search on the create page** hands its choice to the same lookup
  instead of reloading.

## Where it is

- `products/api/openfoodfacts/services.py`: `send_ingredients_text_to_off`,
  `off_write_configured`; `schemas.OFFWriteAnswerSchema`; `inbound.SendLabelIn`.
- `products/views.py`: `OffLookup`, `lookup_from_off` (what `initial_from_off` and
  `OffLookupView` share, notices returned instead of sent to `messages`),
  `OffLookupView`, `SendLabelView`, `product_form_config(can_send_to_off=)`.
- `products/forms.py`: the button, the review slot, the always-present text block,
  the save gate. Templates `components/ingredients_text.html`, `off_review.html`.
- `frontend/.../form/off-lookup.js` (new, replaces `barcode-actions.js`),
  `ingredients-text.js` (editor, send, `load`), `off-search.js` (`onChoose`).
- Settings `OFF_USER_ID`, `OFF_PASSWORD`, `OFF_WRITE_URL` (`config/settings/base.py`;
  the test settings empty the first two). `docs/deployment.md`.

## Checked

2042 pytest, 528 vitest, ruff/basedpyright/pre-commit clean on what I touched. In
Chromium on a throwaway product and user (deleted afterwards, reference counts
unchanged): the panel, taking part of it, the page not reloading, a correction saved
with its ingredients, a real read-only lookup on a new product, a list typed by hand,
asking twice ("same"), and the send button with its answer mocked.

**Not done: a real send to OpenFoodFacts.** No account is configured and nothing was
sent to their database; the write was only exercised with `requests.post` mocked. Try
it first on the staging site (`OFF_WRITE_URL`, see `docs/deployment.md`).

## After the batch

- The estimate card on the edit page is stale until Save (as for the places).
- Keyboard-only use of the places is still not done.
- A text sent is not read back: OpenFoodFacts may re-parse or hold it for review.
- Photo: the lookup offers OpenFoodFacts' photo to the product; nothing is sent back.
