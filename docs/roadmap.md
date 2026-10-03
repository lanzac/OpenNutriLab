# Roadmap

Planned changes that are decided but not started, and why. Remove an entry
once it is done.

## Estimate a product's nutrients from its ingredients

The core feature: deduce a product's vitamins (and minerals, fatty acids...)
from its ingredients, each linked to a reference ingredient whose
composition is known, and check the result against the values the label
declares. The data model is in place (`opennutrilab/products/models.py`);
none of the following is built yet.

- **Reference data.** Import the CIQUAL table (ANSES, open licence: its
  attribution must be shown) as a `Source` with its `SourceFood` entries.
  Its values must keep their meaning: "-" is _not measured_ (empty, never
  0), "< x" is below the detection limit, "traces" is traces, and each value
  has a confidence grade A to D. Other sources will follow.
- **Reference ingredients.** Curated (`ReferenceIngredient`, e.g. "carotte
  crue"), each drawing on several source foods. The rule that aggregates
  their values into one composition - weighting by confidence, for
  instance - is to be decided.
- **Linking ingredients.** How a product ingredient gets its reference
  ingredient is to be designed. OpenFoodFacts' CIQUAL code is stored on
  each ingredient as raw data and may serve as a hint; nothing links
  automatically today.
- **Undeclared percentages.** Most ingredients have no percentage on the
  label. Estimate them in-house - not from OpenFoodFacts' own estimates -
  for instance from the label order (decreasing weight), the declared
  percentages, and the declared nutrition values the result must match.
- **Sub-ingredients.** Decide how a tree is computed: typically the finest
  level that is linked to a reference, without counting a parent and its
  children twice. Labels also vary on whether a sub-ingredient's
  percentage is of its parent or of the whole product.
- **Derived nutrients.** Fill `NutrientComponent`: vitamin A in retinol
  equivalents (retinol + beta-carotene / 6, as CIQUAL gives them
  separately), vitamin K (K1 + K2), and others.
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
