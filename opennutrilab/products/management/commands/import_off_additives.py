import json
from pathlib import Path
from typing import Any
from typing import cast
from typing import override

import requests
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser

from opennutrilab.products.api.openfoodfacts.services import OFF_HEADERS
from opennutrilab.products.models import Additive
from opennutrilab.products.services.additive_import import OFF_SOURCE
from opennutrilab.products.services.additive_import import additives_of_taxonomy
from opennutrilab.products.services.additive_import import import_additives

# The whole taxonomy as one JSON file (about 1 MB), keyed by tag id.
ADDITIVES_URL = "https://static.openfoodfacts.org/data/taxonomies/additives.json"


def read_additives(path: Path | None) -> dict[str, Any]:
    """The taxonomy of additives, from a local file, or else downloaded from OFF."""
    try:
        if path is None:
            response = requests.get(ADDITIVES_URL, timeout=120, headers=OFF_HEADERS)
            response.raise_for_status()
            data = response.json()
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, requests.RequestException, ValueError) as e:
        msg = f"Could not read the additives from {path or ADDITIVES_URL}: {e}"
        raise CommandError(msg) from e
    if not isinstance(data, dict):
        msg = "Not an OpenFoodFacts taxonomy: expected an object keyed by tag id."
        raise CommandError(msg)
    return cast("dict[str, Any]", data)


class Command(BaseCommand):
    help = (
        "Complete the names of the additives that are in the table, with those of "
        "OpenFoodFacts' taxonomy of additives (it gives the French ones, which the "
        "Union list does not). It creates nothing: the additives come from "
        "import_eu_additives. An additive that has a name keeps it. Downloads the "
        "taxonomy unless --path is given."
    )

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--path",
            type=Path,
            help="A local copy of additives.json, instead of downloading it.",
        )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        if not Additive.objects.exists():
            msg = "There is no additive to complete: run import_eu_additives first."
            raise CommandError(msg)
        imported, _skipped = additives_of_taxonomy(read_additives(options["path"]))
        report = import_additives(imported, source=OFF_SOURCE, create=False)
        self.stdout.write(
            self.style.SUCCESS(
                f"{report.completed} additive(s) completed with names, "
                f"{report.unchanged} already complete, {report.shared_names} name(s) "
                "left off an additive that shares it."
            )
        )
