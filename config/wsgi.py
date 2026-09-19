"""
WSGI config for opennutrilab project.

It exposes the WSGI callable as a module-level variable named ``application``.

The application is served over ASGI (see ``config/asgi.py``), which is what the
``/start`` scripts launch. This module exists because ``WSGI_APPLICATION`` in
``config/settings/base.py`` points at it: ``manage.py runserver`` and any
WSGI-based deployment resolve that setting and fail without it.

For more information on this file, see
https://docs.djangoproject.com/en/dev/howto/deployment/wsgi/
"""

import os
import sys
from pathlib import Path

from django.core.wsgi import get_wsgi_application

# This allows easy placement of apps within the interior
# opennutrilab directory.
BASE_DIR = Path(__file__).resolve(strict=True).parent.parent
sys.path.append(str(BASE_DIR / "opennutrilab"))

# If DJANGO_SETTINGS_MODULE is unset, default to the local settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

# This application object is used by any WSGI server configured to use this
# file.
application = get_wsgi_application()
