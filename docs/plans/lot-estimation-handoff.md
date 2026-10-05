# Estimation des nutriments : point de reprise (2026-10-05)

Note pour reprendre le travail dans une nouvelle session. Le plan de
référence reste `docs/plans/lot-estimation.md` (décisions, étapes, écarts) ; ce
fichier dit où l'on s'est arrêté et ce qui reste. À supprimer quand l'étape 10
sera faite.

Pour reprendre, dire par exemple : « Lis `docs/plans/lot-estimation.md` et
`docs/plans/lot-estimation-handoff.md`, puis continue à l'étape 10. »

## Où on en est

Étapes 1 à 9 du plan faites, sur `main`, dernier commit de code `2123966`. 487
tests passent, ruff et pre-commit sont propres,
basedpyright a 8 erreurs qui datent d'avant (toutes dans
`products/tests/test_views.py`).

| Étape | Commit           | Contenu                                                          |
| ----- | ---------------- | ---------------------------------------------------------------- |
| 1     | 98bc243          | Un ingrédient est sa référence (plus de nom ni de colonnes OFF)  |
| 2     | bc3561e          | Import de CIQUAL 2025 (`manage.py import_ciqual`)                |
| 3     | 2ad5395          | Nutriments dérivés (vitamine A, folates, sel, vitamine K)        |
| 4     | 862f2e1          | Composition d'une référence (`reference_composition`)            |
| 5     | d2e3f95, a3bf3da | Curation dans l'admin, propositions d'aliments CIQUAL            |
| 6     | e633f94          | Estimation des pourcentages non déclarés                         |
| 7     | e0abc01          | Calcul des nutriments du produit                                 |
| 8     | dc03d4b          | Validation contre l'étiquette et confiance (`validate_estimate`) |
| 9     | 2123966          | Endpoint `/estimate`, tableau sur la page d'édition, attribution |

Les ingrédients sont lus uniquement dans le texte brut de l'étiquette
(`services/label_parser.py`, commit 75621f5) ; un texte mal lu est signalé et la
lecture s'arrête, sans réparation.

## Ce que fait le code (étapes 6 et 7)

- `services/percentage_estimation.py` : `estimate_percentages(product)` donne,
  par ingrédient (sous-ingrédients compris), `Interval(low, point, high)` en
  pourcentage du produit. Règles, toutes linéaires : les ingrédients du haut
  font 100 (seulement si l'un est non déclaré), les sous-ingrédients font leur
  parent, un pourcentage déclaré vaut à son arrondi près (un sous-ingrédient :
  part de son parent), l'ordre de la liste est décroissant, et pour chacun de
  gras, saturés, glucides, sucres, fibres, protéines et sel de l'étiquette, les
  compositions peuvent donner la valeur déclarée (l'énergie n'est pas une
  règle : elle se déduit des autres). Le minimum et le maximum de chaque part
  sont deux programmes linéaires (scipy, HiGHS). Le point est le milieu de
  combinaisons extrêmes dans 32 directions tirées une fois au hasard (même
  graine), un ingrédient déclaré gardant son chiffre.
- Quand les règles ne tiennent pas, rien n'est deviné et un avertissement dit
  pourquoi : ingrédient sans composition (nommé), produit sans nutrition,
  étiquette que les compositions ne peuvent pas donner (nutriments nommés),
  pourcentages et ordre contradictoires (aucune estimation).
- `services/nutrient_estimation.py` : `estimate_nutrients(product)` donne, par
  nutriment pour 100 g, `NutrientAmount(amount, low, high, coverage)`. Le
  minimum et le maximum sont des programmes linéaires sur les mêmes
  combinaisons que les pourcentages. Un nutriment absent d'un ingrédient n'est
  pas zéro : la couverture dit quelle part des 100 g a une valeur, la quantité et
  le minimum comptent le reste pour rien, et `high` vaut `None` sauf si
  l'ingrédient donne le nutriment dont celui-ci fait partie.
- **Niveau retenu par branche : le plus gros qui a une composition** (le
  parent, « raisins secs », pas ses enfants crus). Les sous-ingrédients ne
  servent que si le parent n'en a pas. C'est une décision de cette session, qui
  remplace « le niveau le plus fin » du plan d'origine.
- scipy et numpy sont des dépendances (acceptées) ; `scipy-stubs` est en dev.

## Ce que fait le code (étape 8)

- `services/estimate_validation.py` : `validate_estimate(product)` charge et
  résout une seule fois, et rend `ValidatedEstimate(nutrients, percentages,
checks, confidence, warnings)`. `warnings` est la liste complète (celles des
  parts d'abord), non bloquantes.
- `checks` : un `Check` par nutriment déclaré (les 8 de l'étiquette et tout autre
  saisi dans l'admin). Le déclaré est un intervalle (son arrondi), l'estimation
  aussi ; ils concordent s'ils se rejoignent, sinon `declared_below` (l'étiquette
  dit moins que ce que les ingrédients apportent au minimum) ou `declared_above`,
  avec l'écart, plus un avertissement (`Problem.DECLARED_BELOW`/`DECLARED_ABOVE`).
  `not_estimated` si aucun ingrédient ne donne le nutriment.
- **L'étiquette est aussi une entrée.** Les sept nutriments que l'étape 6 prend
  comme règles concordent par construction quand elle a servi : le `Check` est
  `constrained` et ne compte pas comme confirmation. Le test indépendant, c'est
  l'énergie et tout nutriment hors des sept. `LABEL_DISAGREES` porte maintenant
  aussi les codes des nutriments (`EstimateWarning.codes`).
- **Vitamine A** : second nutriment dérivé `vitamin_a_sixth` (rétinol + bêta-
  carotène / 6) ; `CONVENTIONS` en fait la seconde lecture de `vitamin_a`, et un
  vitamine A déclarée est comparée à l'enveloppe des deux. Rien ne déclare de
  vitamine hors admin pour l'instant : testé, pas vu sur un vrai produit.
- `confidence` : par nutriment estimé, quatre parts entre 0 et 1 (couverture,
  qualité, incertitude, accord) et un score qui est leur produit (l'incertitude
  compte en `1 - x`). Formules dans la docstring du module.
- Sur le muesli : 0,7 s ; l'énergie déclarée (1532 kJ) est dans 1416-1739 ; aucun
  avertissement ; incertitude 0,07 ; protéines 0,46, vitamine C 0,26, fer 0,32.

## Ce que fait le code (étape 9)

- `services/estimate_report.py` : `build_estimate(product)` donne un `EstimateOut`
  (schéma dans `api/schemas/outbound.py`) que l'endpoint rend tel quel et que la
  page affiche : la présentation n'est écrite qu'une fois. Par nutriment : estimé
  (bas, point, haut ; haut `null` si aucun maximum connu), couverture, confiance
  et ses quatre parts, déclaré (avec son arrondi) et `check`. La vitamine A est
  une seule entrée, sa seconde lecture est dans `other_readings`. S'y ajoutent les
  avertissements, les `sources` avec leur attribution et la réserve sur les
  transformations (`caveat`).
- `GET /api/v1/products/{barcode}/estimate` (`api/routes.py`) : lecture seule,
  même authentification que le reste de l'API (session ou jeton de l'appli).
- **Écart avec le plan** : `estimated` d'un ingrédient vaut `null` quand
  l'étiquette se contredit (rien n'a pu être estimé), au lieu d'être toujours là.
- Page : une carte sous le formulaire, sur la page d'édition (`product_form.html`,
  `components/estimate.html`, filtres dans `templatetags/estimate_tags.py`), dans
  sa propre rangée pleine largeur (dans la colonne du formulaire elle faisait
  13 000 px de haut). Calculée à chaque GET (environ 1 s pour le muesli), jamais
  après un POST refusé ; un `RuntimeError` du solveur est journalisé et la page
  dit que l'estimation n'a pas pu être calculée au lieu de casser.
- L'attribution CIQUAL est dans la réponse, sur la page et sous la composition
  d'une référence dans l'admin (elle n'y était pas).
- Vérifié dans Chromium sur le muesli, en anglais et en français : aucune erreur de
  console, aucune requête en échec, pas de débordement, 83 lignes.
- Traductions : les 22 entrées des étapes 8 et 9 sont dans `django.po` (insérées à
  la main, sans régénérer le catalogue) et `django.mo` est recompilé.

## État de la base de dev (pas dans le code)

- Source `Manual` créée par toi, avec trois aliments ajoutés : `soy-flakes`,
  `wheat-flakes`, `freeze-dried-mixed-berries`, reliés aux références « flocons
  de soja », « flocons de blé » et « fruits rouges lyophilisés » (restées « à
  relire »). Chacun est calculé d'après des aliments CIQUAL (20901 ; 9060 ;
  groseille, cassis, framboise crus à 4 % d'eau), avec les 8 nutriments de
  l'étiquette, note D, intervalle d'au moins ±15 %. La provenance n'est que dans
  le nom de l'aliment.
- **Ces données vivent dans la base, comme les références validées** : une
  réinitialisation de la base les perd. Rien ne les recrée par le code.
- `vitamin_a_sixth` a été créé dans la base de dev par un appel direct à
  `ensure_derivations()` ; `import_ciqual` le fait aussi, une réinitialisation
  de la base le perd donc tant qu'on ne relance pas l'import.
- Muesli `3229820794556` : 13 références, 8 validées. Avec l'ordre de la liste :
  flocons de blé 28,77 à 31,50 %, avoine 24,43 à 29,91 %, raisins 1,35 à 3,54 %,
  sarrasin 0 à 1,45 %. Tous les nutriments de l'étiquette ont un intervalle qui
  contient le chiffre déclaré. Les vitamines ne sont couvertes que pour 36 à
  38 % du produit.

## Limites connues

- Pas de perte d'eau ni de transformation : un produit cuit ou séché sort du
  cadre de la règle de nutrition.
- **CIQUAL note l'énergie D pour 2 842 aliments sur 2 843** (valeur calculée) : la
  qualité de l'énergie de tout produit est donc 0,25 et son score au plus 0,25.
  C'est la note de la source, prise telle quelle. À trancher : lui faire prendre
  la qualité des nutriments dont elle se calcule ?
- Un zéro déclaré n'a pas de marge (une étiquette « 0 g » peut dire moins de
  0,5 g) et les tolérances que l'UE admet entre étiquette et aliment ne s'ajoutent
  pas à l'arrondi : l'écart signalé peut venir de là. Même règle qu'à l'étape 6.
- L'ordre décroissant (règlement 1169/2011, art. 18) a des exceptions qu'un
  texte ne montre pas ; elles ne peuvent que rendre un résultat trop étroit.
- Une composition n'est prise que si elle a gras, glucides et protéines.
- Le point central dépend de la graine ; il peut bouger un peu si les données
  changent. Les intervalles, eux, sont exacts.
- Une même référence ne peut apparaître qu'une fois sous un même parent (contrainte
  d'unicité) ; les pluriels des noms ne sont gérés que par la suppression d'un
  « s », sans accents.

## Ce qui reste

À décider avec toi :

1. **Compléter les trois aliments manuels** avec toutes les valeurs de leurs
   aliments CIQUAL de référence (vitamines, minéraux), même méthode (note D,
   ±15 %), pour que la couverture passe à presque 100 %. Proposé, pas fait :
   tu avais demandé les macronutriments seulement.
2. **Un graphique** : des barres d'intervalle par nutriment avec le déclaré
   marqué dessus, en réutilisant `nutrient-chart.js`. Proposé, pas décidé : le
   tableau de l'étape 9 est volontairement simple, le vrai panneau est au lot 3.
3. Les décisions 6 (calcul à la demande, sans table) et 7 (formule de
   confiance) du plan ne sont pas confirmées. La 7 est codée telle que
   recommandée (parts visibles, score = produit) ; l'échelle des notes et le
   produit sont à un seul endroit du code si tu veux les changer.
4. Les deux limites ci-dessus (énergie notée D, zéro sans marge).
5. Le tableau liste les 69 nutriments, la plupart couverts à 37 % : long mais
   honnête. À restreindre ou à regrouper au lot 3 ?

Étapes du plan :

- **10. Docs.** La feuille de route (`docs/roadmap.md`) a déjà été mise à jour pour
  les étapes 8 et 9, et les traductions de ces deux étapes sont faites. Reste :
  relire la feuille de route une dernière fois, `save` (jamais traduit) et
  l'entrée « fuzzy » `Other` du catalogue (sa traduction est celle de `Others`),
  puis supprimer cette note.
- **Lot 3** (`docs/plans/lot-3-react-form.md`) : formulaire produit en React,
  avec le vrai panneau d'estimation (étape 5 de ce lot).

Autre reste : trancher le sort des références inutilisées, éventuellement les
supprimer.

## Pour travailler ici

- Le terminal de la session tourne dans le conteneur Django. Pour lancer les
  tests (ou `manage.py shell`) depuis `/app` :

  ```bash
  eval "$(sed -E '/^#|^$/d; s/^([A-Z_]+)[[:space:]]*=[[:space:]]*(.*)$/export \1="\2"/' .envs/.local/.postgres)"
  export DATABASE_URL="postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}" USE_DOCKER=no
  .venv/bin/pytest
  ```

- Le hook git pre-commit n'est pas installé : lancer `.venv/bin/pre-commit run`
  sur les fichiers indexés avant de committer, et ne jamais enchaîner les deux
  avec `;`.
- Les scripts du répertoire temporaire de session sont perdus à la
  reconstruction du conteneur.
- La mémoire de Claude (`MEMORY.md`, fichier « Project goal: nutrient
  estimation ») contient déjà ces faits ; ce fichier-ci est la version à lire.
