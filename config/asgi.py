"""
ASGI config for opennutrilab project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/dev/howto/deployment/asgi/
"""

import logging
import os

from django.conf import settings
from django.core.asgi import get_asgi_application

# If DJANGO_SETTINGS_MODULE is unset, default to the local settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

# --- Debugger hook (only in DEBUG mode) ---
if settings.DEBUG:
    try:
        import debugpy

        debugpy.listen(("127.0.0.1", 5678))

        logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
        logging.info("✅ debugpy is listening on 127.0.0.1:5678 (from asgi.py)")
        # Uncomment if you want Django to wait for VSCode debugger before continuing:
        # debugpy.wait_for_client()
    except Exception:
        logging.exception("❌ Failed to start debugpy")
# --- End debugger hook ---

# This application object is used by any ASGI server configured to use this file.
application = get_asgi_application()
