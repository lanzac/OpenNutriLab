"""
Guards the django-vite / DEBUG coupling across settings modules.

base.py builds the DJANGO_VITE dict while DEBUG still holds its env-driven
default, so any module that flips DEBUG afterwards has to re-derive dev_mode
too. Getting that wrong is invisible to the rest of the suite, because
config.settings.test pins dev_mode to True: every template renders fine under
pytest while local development raises DjangoViteAssetNotFoundError on any
{% vite_asset %}.

The check runs in a subprocess on purpose. DJANGO_VITE is a single dict shared
by reference across the settings modules, so config.settings.test has already
mutated dev_mode in this interpreter - importing config.settings.local here
would read that mutation instead of what the module actually configures.
"""

import json
import os
import subprocess
import sys

import pytest

PROBE = """
import django
django.setup()
from django.conf import settings
import json
print(json.dumps({
    "debug": settings.DEBUG,
    "dev_mode": settings.DJANGO_VITE["default"]["dev_mode"],
}))
"""


@pytest.mark.parametrize("settings_module", ["config.settings.local"])
def test_dev_mode_tracks_debug(settings_module: str):
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", PROBE],
        capture_output=True,
        text=True,
        timeout=120,
        env={"DJANGO_SETTINGS_MODULE": settings_module, **_inherited_env()},
        check=False,
    )
    assert result.returncode == 0, f"could not load {settings_module}:\n{result.stderr}"

    config = json.loads(result.stdout.strip().splitlines()[-1])
    assert config["dev_mode"] == config["debug"], (
        f"{settings_module} leaves DJANGO_VITE dev_mode ({config['dev_mode']}) out "
        f"of sync with DEBUG ({config['debug']}); re-derive it after setting DEBUG."
    )


def _inherited_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "DJANGO_SETTINGS_MODULE"}
    # local.py reads USE_DOCKER with no default and blows up when it is unset,
    # so the probe must not depend on the ambient devcontainer environment.
    # "no" simply skips the docker-specific INTERNAL_IPS block, which has no
    # bearing on the setting under test.
    env["USE_DOCKER"] = "no"
    return env
