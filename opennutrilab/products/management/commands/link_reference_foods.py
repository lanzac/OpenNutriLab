import json
from pathlib import Path
from typing import Any
from typing import override

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser
from django.db import transaction

from opennutrilab.products.models import SourceFood
from opennutrilab.products.services.custom_foods import CustomFoodError
from opennutrilab.products.services.reference_links import ReferenceLink
from opennutrilab.products.services.reference_links import link_reference_foods
from opennutrilab.products.services.reference_links import parse_links

LINKS_FILE = Path(__file__).parents[2] / "data" / "reference_links.json"


class Command(BaseCommand):
    help = (
        "Link reference ingredients to the foods of a table, from a JSON file of "
        '[{"reference": name, "foods": [{"source": code, "code": code}]}]. By '
        "default the file is products/data/reference_links.json, which keeps the "
        "links a person made so that a reset of the database does not lose them "
        "(run it once CIQUAL is imported and the products are loaded, so that the "
        "references exist). It only adds the links that are missing. --dry-run "
        "keeps nothing."
    )

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "links",
            type=Path,
            nargs="?",
            default=LINKS_FILE,
            help="JSON file of links (default: products/data/reference_links.json).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Say what would be linked, and keep nothing.",
        )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        links = _read(options["links"])
        dry_run: bool = options["dry_run"]
        added = already = 0
        failures: list[str] = []

        with transaction.atomic():
            for link in links:
                try:
                    result = link_reference_foods(link)
                except CustomFoodError as e:
                    failures.append(f"{link.reference!r}: {e}")
                    self.stdout.write(self.style.ERROR(failures[-1]))
                    continue
                name = f"{result.reference.pk} {result.reference.name}"
                for food in result.added:
                    self.stdout.write(f"Linked {name}: {food.code} {_name(food)}")
                for food in result.already:
                    self.stdout.write(f"Already linked {name}: {food.code}")
                added += len(result.added)
                already += len(result.already)
            if dry_run:
                transaction.set_rollback(True)

        summary = f"{added} link(s) made, {already} already there."
        if failures:
            msg = f"{len(failures)} link(s) not made, {summary}\n" + "\n".join(failures)
            raise CommandError(msg)
        self.stdout.write(
            self.style.SUCCESS(
                f"Dry run, nothing kept. {summary}" if dry_run else summary
            )
        )


def _name(food: SourceFood) -> str:
    return food.name_fr or food.name_en


def _read(path: Path) -> list[ReferenceLink]:
    try:
        return parse_links(json.loads(path.read_text(encoding="utf-8")))
    except OSError as e:
        msg = f"Cannot read {path}: {e}"
        raise CommandError(msg) from e
    except (ValueError, CustomFoodError) as e:
        msg = f"{path}: {e}"
        raise CommandError(msg) from e
