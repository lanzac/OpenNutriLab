#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys
import logging



def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nutrilibre.settings')

    # Setup logging to stdout (so Docker logs and dev logs work)
    logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

    # start debug section
    from django.conf import settings

    if settings.DEBUG:
        if os.environ.get('RUN_MAIN') or os.environ.get('WERKZEUG_RUN_MAIN'):
            import debugpy
            debugpy.listen(("0.0.0.0", 5678))
            logging.info("debugpy is listening on 0.0.0.0:5678") # we use logging instead of print to ensure it works in all environments
            # debugpy.wait_for_client()  # Uncomment to wait for VSCode debugger to attach before continuing
    else:
        logging.info("Debug mode is off. Debugging will not be available.")
    # end debug section

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        logging.error("Couldn't import Django. Are you sure it's installed and available on your PYTHONPATH environment variable? Did you forget to activate a virtual environment?")
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
