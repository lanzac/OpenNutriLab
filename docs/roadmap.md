# Roadmap

Planned changes that are decided but not started, and why. Remove an entry
once it is done.

## Estimate a product's nutrients from its ingredients

The core feature: deduce a product's vitamins (and minerals, fatty acids...)
from its ingredients, each linked to a reference ingredient whose
composition is known, and check the result against the values the label
declares. The data model is in place (`opennutrilab/products/models.py`), the
CIQUAL table is imported and an ingredient is linked to its reference; the
rest of the following is not built yet.

- **Reference data.** The CIQUAL 2025 table is imported (`manage.py
import_ciqual`). Other sources will follow, each with its own importer and
  the attribution its licence requires.
- **Reference ingredients.** Curated (`ReferenceIngredient`, e.g. "carotte
  crue"), each drawing on several source foods. The rule that aggregates
  their values into one composition - weighting by confidence, for
  instance - is to be decided.
- **Linking ingredients.** An ingredient is its reference ingredient:
  `Ingredient` keeps no name and no OpenFoodFacts data, only the link, found
  by the ingredient's normalized name among the references' own (unique)
  names, and a name that matches nothing creates a reference marked _to
  review_. That is built. What is missing: the CIQUAL import, so that a
  created reference can be seeded with OFF's CIQUAL code when it is a known
  food (OFF's codes are suggestions, never trusted), and the tools to curate
  the references to review. The plan is in `docs/plans/lot-estimation.md`.
- **Undeclared percentages.** Most ingredients have no percentage on the
  label. Estimate them in-house - not from OpenFoodFacts' own estimates -
  for instance from the label order (decreasing weight), the declared
  percentages, and the declared nutrition values the result must match.
- **Sub-ingredients.** Decide how a tree is computed: typically the finest
  level that is linked to a reference, without counting a parent and its
  children twice. Labels also vary on whether a sub-ingredient's
  percentage is of its parent or of the whole product.
- **Vitamin A on labels.** The derived vitamin A follows CIQUAL (retinol +
  beta-carotene / 12). Check which convention EU labels use (a sixth, if the
  regulation says so), because declared and estimated vitamin A are only
  comparable if they are the same quantity.
- **Reporting.** Every estimate comes with its coverage (the share of the
  product with a known composition) and its comparison with the declared
  values. Processing (drying, cooking) changes compositions and destroys
  part of some vitamins: the result stays an estimate.

## Upgrade to Django 6.0, for background tasks

The project is on Django 5.2 (`django<6.0` in `pyproject.toml`).

Django 6.0 added a built-in tasks framework (`django.tasks`): code declares
tasks and enqueues them through one API, whatever runs them. Django itself
only ships backends for development and tests; running tasks for real needs
a third-party backend and its worker (for instance the database backend of
the `django-tasks` package, which needs no extra service).

**Why it matters here:** two things still run inside the HTTP request and
would be better off in the background:

- **The OpenFoodFacts product photo** is downloaded while the product is
  saved, with a 10-second timeout, from an image host that is sometimes
  unreachable while the OpenFoodFacts API answers. Each wait holds a server
  worker, and a failure can only be reported, not retried
  (`opennutrilab/products/services/product_services.py`, `download_image`).
- **Emails** (account verification, password reset) are sent synchronously
  over SMTP.

Celery was removed in October 2026 because nothing used it: it cost two
production containers and a broker for no task at all. When these tasks are
moved to the background, prefer the Django 6.0 framework to reinstating
Celery, unless the needs by then call for Celery's scheduling or routing.
