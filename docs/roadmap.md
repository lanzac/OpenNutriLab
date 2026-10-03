# Roadmap

Planned changes that are decided but not started, and why. Remove an entry
once it is done.

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
  (`products/services/product_services.py`, `download_image`).
- **Emails** (account verification, password reset) are sent synchronously
  over SMTP.

Celery was removed in October 2026 because nothing used it: it cost two
production containers and a broker for no task at all. When these tasks are
moved to the background, prefer the Django 6.0 framework to reinstating
Celery, unless the needs by then call for Celery's scheduling or routing.
