"""
The project's single HTTP API, mounted at /api/v1/ (see config/urls.py).

Every route needs an authenticated user, by one of two means:
- the Django session cookie, for the site's own pages and a same-origin
  SPA. With it, django-ninja also enforces CSRF on every write;
- django-allauth's X-Session-Token header, for the mobile app, which logs
  in through allauth's headless API under /_allauth/app/v1/ and sends back
  the session token it receives.
"""

from allauth.headless.contrib.ninja.security import x_session_token_auth
from django.contrib.admin.views.decorators import staff_member_required
from ninja import NinjaAPI
from ninja.security import django_auth

from products.api.routes import router as products_router

api = NinjaAPI(
    title="OpenNutriLab API",
    version="1",
    urls_namespace="api",
    auth=[django_auth, x_session_token_auth],
    # The interactive docs and the OpenAPI schema, for staff only.
    docs_decorator=staff_member_required,
)
api.add_router("/products/", products_router)
