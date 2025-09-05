"""
ASGI config for opennutrilab project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/dev/howto/deployment/asgi/
"""

import logging
import os
import sys
from pathlib import Path

from django.conf import settings
from django.core.asgi import get_asgi_application

# This allows easy placement of apps within the interior
# opennutrilab directory.
BASE_DIR = Path(__file__).resolve(strict=True).parent.parent
sys.path.append(str(BASE_DIR / "opennutrilab"))

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
    except Exception as e:
        logging.error(f"❌ Failed to start debugpy: {e}")
# --- End debugger hook ---

# This application object is used by any ASGI server configured to use this file.
django_application = get_asgi_application()

# Import websocket application here, so apps from django_application are loaded first
from config.websocket import websocket_application  # noqa: E402


async def application(scope, receive, send):
    if scope["type"] == "http":
        await django_application(scope, receive, send)
    elif scope["type"] == "websocket":
        await websocket_application(scope, receive, send)
    else:
        msg = f"Unknown scope type {scope['type']}"
        raise NotImplementedError(msg)
