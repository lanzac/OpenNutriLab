# Plan: lot 3, the product form in React

Status: planned, not started (written 2026-10-03). Best done after the
estimation batch, so that the form can show the estimate and the
ingredient-to-reference linking.

## Goal

Replace the server-rendered product form with a React page that talks only
to `/api/v1/`. Today the form is built from:

- crispy-forms and vanilla-views (`forms.py`, `views.py`);
- vanilla JS (`frontend/src/apps/products/form/`);
- hidden `off_*` fields that carry OFF data from the GET to the POST.

This is a step towards the API-only endgame (see the Vite/React migration
plan): Django keeps the page shell, and React owns the form.

## Decisions to take at the start of the session

1. **Image upload through the API.** `ProductCreate` is JSON today.
   _Recommendation:_ keep JSON for the data, and add a separate multipart
   endpoint `POST /api/v1/products/{barcode}/image`. The OFF image URL stays
   in JSON and is downloaded server-side, as it is now (with the allowlist).
2. **OFF lookup endpoint.** No API route exists yet.
   _Recommendation:_ add `GET /api/v1/off/{barcode}`. It returns a
   `ProductCreate`-shaped draft, made from `fetch_from_off`,
   `declared_nutrients_from_off` and `to_ingredient_inputs`, and nothing is
   saved. This replaces the `off_*` hidden fields.
3. **Ingredient tree editor.** Options:
   - keep Tabulator, wrapped in a React component;
   - rewrite it as plain React.

   _Recommendation:_ keep Tabulator for now. It works and is tested, and
   a rewrite does not change behaviour.

4. **Form state and validation.** _Recommendation:_ plain React state plus
   a small hook, with no form library. The server stays the validator: 422
   errors are mapped to fields.
5. **What leaves the backend.**
   - `ProductForm` and the `products` crispy layouts are removed.
   - `django-vanilla-views` is removed if nothing else uses it.
   - `crispy-forms` stays only if `users/` or allauth templates still need
     it. Check this first with `grep -r crispy opennutrilab/`.

## Steps

1. **API additions**: the OFF draft endpoint, the image endpoint, and a
   `GET /api/v1/nutrients?on_label=1` that serves the catalogue (code,
   name, unit, parent). The form builds its fields from the catalogue,
   never from a hardcoded list. Tests go with each route.
2. **Translated labels**: keep the current `|json_script` labels dict. The
   `.po` stays the single source; react-i18next is Phase 4, not this lot.
3. **React page**, a `product-form` Vite entry mounted in
   `product_form.html`, with these components:
   - barcode field with OFF lookup and reset;
   - name and description;
   - image preview, with the OFF photo first, then upload;
   - declared nutrient inputs from the catalogue;
   - nutrient chart, using the existing `nutrient-chart.js` functions;
   - ingredient tree;
   - non-blocking warnings, using the same rules as
     `declared_value_warnings`. Expose them from the API response rather
     than duplicating them in JS.
4. **Create and edit flows**: POST or PATCH, then redirect to the list
   with a message. Handle 409 (barcode exists), 422 and 404 (OFF unknown)
   the same way the current notices do.
5. **If the estimation batch is done**:
   - an estimate panel (values, ranges, coverage, confidence, comparison
     with the declared values);
   - per-ingredient reference linking with accept or reject of the
     suggestions.
6. **Removal**: the old views, `ProductForm`, the crispy layouts, the
   `off_*` plumbing, the obsolete tests, the `.po` entries, and the
   dependencies. Keep the tests that describe behaviour and port them to
   API or vitest tests.
7. **i18n debt**: resolve the remaining `TODO(i18n)` (Tabulator titles,
   Plotly labels, the French `alert()` in barcode-actions).

## Done when

- Creating and editing the muesli `3229820794556` from OFF works in a real
  browser, including the photo, the nutrients and the ingredient tree.
- There are no console errors in either theme.
- Backend tests, vitest, basedpyright and pre-commit all pass. The
  production build path has been checked, since the new Vite entry appears
  in the manifest.
