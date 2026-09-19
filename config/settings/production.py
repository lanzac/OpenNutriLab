# ruff: noqa: E501
"""Production settings.

Nothing here is specific to a hosting provider: every value that changes from
one machine to the next is read from the environment, so the same image runs on
a VPS, on a managed container platform, or in CI. See docs/deployment.rst.
"""

from .base import *  # noqa: F403
from .base import APPS_DIR
from .base import DATABASES
from .base import DJANGO_VITE
from .base import REDIS_SSL
from .base import REDIS_URL
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = False
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
# Deliberately without a default: a production process that starts with a
# guessable key is worse than one that refuses to start at all.
SECRET_KEY = env("DJANGO_SECRET_KEY")
# https://docs.djangoproject.com/en/dev/ref/settings/#allowed-hosts
# Comma-separated, e.g. "opennutrilab.org,www.opennutrilab.org". A leading dot
# matches every subdomain (".opennutrilab.org").
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")

# DATABASES
# ------------------------------------------------------------------------------
# base.py already builds DATABASES from DATABASE_URL, which works for both the
# bundled postgres container and a managed database.
# https://docs.djangoproject.com/en/dev/ref/settings/#conn-max-age
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)
# Postgres over the public internet (a managed database) needs TLS; the bundled
# container talks over a private compose network and does not.
if env.bool("DJANGO_DATABASE_SSL_REQUIRE", default=False):
    DATABASES["default"].setdefault("OPTIONS", {})["sslmode"] = "require"

# CACHES
# ------------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            # A cache outage should slow the site down, not take it offline.
            "IGNORE_EXCEPTIONS": True,
        },
    },
}
if REDIS_SSL:
    CACHES["default"]["OPTIONS"]["CONNECTION_POOL_KWARGS"] = {"ssl_cert_reqs": None}

# SECURITY
# ------------------------------------------------------------------------------
# The app never terminates TLS itself; a reverse proxy does and forwards the
# original scheme. Without this Django believes every request is plain HTTP and
# redirects forever.
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-proxy-ssl-header
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-ssl-redirect
# Only ever set to False for a smoke test that speaks HTTP to the container
# directly, as CI does.
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
# https://docs.djangoproject.com/en/dev/ref/settings/#session-cookie-secure
SESSION_COOKIE_SECURE = True
# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-cookie-secure
CSRF_COOKIE_SECURE = True
# https://docs.djangoproject.com/en/dev/topics/security/#ssl-https
# Starts low on purpose. HSTS is not revocable: once a browser has seen this
# header it refuses plain HTTP for the whole duration, so raise it in steps
# (60 -> 3600 -> 86400 -> 31536000) only once HTTPS is known to be stable.
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=60)
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-hsts-include-subdomains
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
    default=True,
)
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-hsts-preload
SECURE_HSTS_PRELOAD = env.bool("DJANGO_SECURE_HSTS_PRELOAD", default=True)
# https://docs.djangoproject.com/en/dev/ref/middleware/#x-content-type-options-nosniff
SECURE_CONTENT_TYPE_NOSNIFF = env.bool(
    "DJANGO_SECURE_CONTENT_TYPE_NOSNIFF",
    default=True,
)
# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-trusted-origins
# Django checks the Origin header against this list, not against ALLOWED_HOSTS,
# so a POST from the site itself is rejected when it is missing. Default to the
# HTTPS origin of each allowed host; ".example.com" becomes "https://*.example.com".
CSRF_TRUSTED_ORIGINS = env.list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    default=[
        f"https://*{host}" if host.startswith(".") else f"https://{host}"
        for host in ALLOWED_HOSTS
        if host != "*"
    ],
)

# CORS
# ------------------------------------------------------------------------------
# base.py restricts CORS to ^/api/.*$. Browsers are what enforce CORS, so this
# matters for the React SPA served from another origin and for a mobile app
# running in a web view (Capacitor sends "capacitor://localhost"); a native
# HTTP client sends no Origin header and is unaffected.
CORS_ALLOWED_ORIGINS = env.list("DJANGO_CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = env.bool("DJANGO_CORS_ALLOW_CREDENTIALS", default=True)

# STATIC & MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#storages
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    # Hashes every filename and writes gzip/brotli siblings, so WhiteNoise can
    # serve the bundle with immutable caching. It also fails the build when a
    # stylesheet references a file that collectstatic did not find, which is
    # exactly the breakage that only shows up under DEBUG=False.
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
# User uploads outlive the container, so they belong on a mounted volume rather
# than inside the image.
MEDIA_ROOT = env("DJANGO_MEDIA_ROOT", default=str(APPS_DIR / "media"))

# django-vite
# ------------------------------------------------------------------------------
# base.py derives dev_mode from the env-driven DEBUG, which is read before the
# DEBUG = False above lands. Re-derive it, otherwise a stray DJANGO_DEBUG=1 in
# the environment makes every {% vite_asset %} point at a dev server that does
# not exist in production. Same trap as the one documented in local.py.
DJANGO_VITE["default"]["dev_mode"] = DEBUG

# EMAIL
# ------------------------------------------------------------------------------
# base.py sets ACCOUNT_EMAIL_VERIFICATION = "mandatory", so nobody can complete
# a signup until these point at a working SMTP server.
# https://docs.djangoproject.com/en/dev/ref/settings/#default-from-email
DEFAULT_FROM_EMAIL = env(
    "DJANGO_DEFAULT_FROM_EMAIL",
    default="OpenNutriLab <noreply@localhost>",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#server-email
SERVER_EMAIL = env("DJANGO_SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)
# https://docs.djangoproject.com/en/dev/ref/settings/#email-subject-prefix
EMAIL_SUBJECT_PREFIX = env(
    "DJANGO_EMAIL_SUBJECT_PREFIX",
    default="[OpenNutriLab] ",
)
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)

# ADMIN
# ------------------------------------------------------------------------------
# Moving the admin off the default path does not secure it, but it does remove
# it from the reach of the bots that hammer /admin/ all day.
ADMIN_URL = env("DJANGO_ADMIN_URL", default="admin/")

# LOGGING
# ------------------------------------------------------------------------------
# Logs go to stdout and are collected by whatever runs the container (docker
# logs, journald, the platform's log viewer). Writing log files from inside a
# container only creates disks to fill.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "level": env("DJANGO_LOG_LEVEL", default="INFO"),
        "handlers": ["console"],
    },
    "loggers": {
        # Unhandled exceptions, which DEBUG=False otherwise swallows into a
        # bare 500 page.
        "django.request": {
            "level": "ERROR",
            "handlers": ["console"],
            "propagate": False,
        },
        "django.security.DisallowedHost": {
            "level": "ERROR",
            "handlers": ["console"],
            "propagate": False,
        },
    },
}
# Your stuff...
# ------------------------------------------------------------------------------
