import json
from pathlib import Path
from typing import Any
from typing import cast
from typing import override

import requests
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser
from django.db import transaction

from opennutrilab.products.api.openfoodfacts.services import OFF_HEADERS
from opennutrilab.products.models import IngredientTaxon

# The whole taxonomy as one JSON file (about 3 MB), keyed by tag id.
TAXONOMY_URL = "https://static.openfoodfacts.org/data/taxonomies/ingredients.json"
BATCH_SIZE = 1_000


def read_taxonomy(path: Path | None) -> dict[str, Any]:
    """The taxonomy, from a local file, or else downloaded from OFF."""
    try:
        if path is None:
            response = requests.get(TAXONOMY_URL, timeout=120, headers=OFF_HEADERS)
            response.raise_for_status()
            data = response.json()
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, requests.RequestException, ValueError) as e:
        msg = f"Could not read the taxonomy from {path or TAXONOMY_URL}: {e}"
        raise CommandError(msg) from e

    if not isinstance(data, dict):
        msg = "Not an OpenFoodFacts taxonomy: expected an object keyed by tag id."
        raise CommandError(msg)
    return cast("dict[str, Any]", data)


def taxon_from_entry(off_id: str, entry: dict[str, Any]) -> IngredientTaxon:
    names: dict[str, Any] = entry.get("name") or {}
    ciqual: dict[str, Any] = entry.get("ciqual_food_code") or {}
    proxy: dict[str, Any] = entry.get("ciqual_proxy_food_code") or {}
    return IngredientTaxon(
        off_id=off_id,
        name_en=str(names.get("en", ""))[:255],
        name_fr=str(names.get("fr", ""))[:255],
        ciqual_food_code=str(ciqual.get("en", ""))[:10],
        ciqual_proxy_food_code=str(proxy.get("en", ""))[:10],
    )


class Command(BaseCommand):
    help = (
        "Load OpenFoodFacts' ingredient taxonomy, which gives the normalized "
        "names of ingredients. Downloads it unless --path is given; running "
        "it again updates what changed."
    )

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--path",
            type=Path,
            help="A local copy of ingredients.json, instead of downloading it.",
        )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        taxonomy = read_taxonomy(options["path"])
        taxa = [taxon_from_entry(off_id, entry) for off_id, entry in taxonomy.items()]

        with transaction.atomic():
            before = IngredientTaxon.objects.count()
            IngredientTaxon.objects.bulk_create(
                taxa,
                batch_size=BATCH_SIZE,
                update_conflicts=True,
                unique_fields=["off_id"],
                update_fields=[
                    "name_en",
                    "name_fr",
                    "ciqual_food_code",
                    "ciqual_proxy_food_code",
                ],
            )
            added = IngredientTaxon.objects.count() - before

        in_english = sum(1 for taxon in taxa if taxon.name_en)
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(taxa)} taxonomy entries loaded ({added} new), "
                f"{in_english} with an English name."
            )
        )
