# Plan: see what was read of the label, and leave places out

Status: built 2026-10-09, not committed. Asked by the user on product 3270160196876
(colin d'Alaska), whose fishing zone `[Theragra chalcogramma … zone de pêche … datage]`
was read as parts of the fish.

## What it does

On the create and edit pages, the ingredient list as the label prints it is shown
with the places the parser **read as ingredients highlighted** (names and
percentages; not the commas, the notes in parentheses, the allergens, the origins, the
class of an additive, nor what follows the list). A person selects a part of the text
and **leaves it out**, or **puts it back**; the text is read again at once and the
table of ingredients and the highlight follow. "Put everything back" empties the
places. Saving the page saves them with the ingredients.

## Ground rules

- **A person can only take places out.** The label's words stay the only source
  (`feedback-label-text-only`): nothing is added to them, nothing is repaired. A text
  that is wrong because of what was taken out (half of a group) is said so, and read as
  nothing, as any badly read text is. What the parser dropped by itself (the end of the
  list, a statement) cannot be put back from the page: that is a text to correct on
  OpenFoodFacts.
- **What is left out is blank to the reading**, which is why what was wrong in it is
  not seen any more (a nutrition table caught in the list can be left out instead of
  stopping the reading). A place left out that empties an item between two commas is not
  an "empty item" warning: the person emptied it.
- **The places are positions in the stored text** (`Product.ingredients_ignored`,
  `[[start, end], …]`, characters as Python counts them). They go with the text: a
  lookup ("Reset data") brings a new text and empties them.

## Where it is

- `services/label_parser.py`: `read_label(text, ignored=())` answers
  `LabelReading.used`, the places read; the parser keeps the position of every piece
  it cuts (the rewrites of a piece, `_without_notes` and `_percent_beside`, blank
  instead of cutting, so positions never move). `_name_spans` does what `_name` does,
  on blanks; a test keeps the two together.
- `Product.ingredients_ignored` and `Product.ingredients_language` (migration 0020).
  The language is the text's, so that a text read again later looks names up in the
  right language ("raisin", "dates"). `reread_ingredients` uses both; `--language`
  still wins when given, and `fr` is the default for a product with none.
- `ReadLabelView` (`POST /products/read-label/`, a page helper, not API): the text
  read again, as the rows of the table, the JSON the form posts, the places read and
  the warnings. Nothing is stored by it.
- The form: hidden `ingredients_ignored` and `ingredients_lc`; a page that was
  corrected posts like a lookup (`off_barcode`, `off_ingredients`,
  `off_ingredients_text`, set by `ingredients-text.js`), so `ProductForm._write_data`
  has one rule for both. The API's `ProductCreate`/`ProductUpdate`/`ProductOut` carry
  the two fields.
- `frontend/.../form/ingredients-text.js` (+ `.css`): the marked text, the selection
  (counted in characters, not UTF-16 units), the calls.

## Not done, to say

- The page's estimate card still shows the stored estimate until the product is saved.
- Selecting needs a mouse or a finger: there is no way yet to select with the keyboard
  alone.
- The highlight of a stored product is what the **present** parser makes of its text,
  which can differ from the tree stored if a rule changed since: `reread_ingredients`
  brings them together.
