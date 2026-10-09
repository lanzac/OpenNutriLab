import json
from pathlib import Path
from typing import Any
from typing import override

from django.core.management.base import BaseCommand
from django.core.management.base import CommandParser

from opennutrilab.products.services.reference_links import LINKS_FILE
from opennutrilab.products.services.reference_links import links_as_data
from opennutrilab.products.services.reference_links import links_to_keep


class Command(BaseCommand):
    help = (
        "Write in a JSON file the links of the reference ingredients to the foods of "
        "a table (CIQUAL...), with the default food of the references that have "
        "forms, so that link_reference_foods can make them again after a reset of "
        "the database. By default the file is products/data/reference_links.json, "
        "which is replaced. The foods made by hand are not written: their specs "
        "link them."
    )

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "path",
            type=Path,
            nargs="?",
            default=LINKS_FILE,
            help="JSON file to write (default: products/data/reference_links.json).",
        )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        path: Path = options["path"]
        kept = links_to_keep()
        path.write_text(
            json.dumps(links_as_data(kept.links), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for reference in kept.unnamed:
            self.stdout.write(
                self.style.WARNING(
                    f"Not written, no name finds it alone: {reference.pk} "
                    f"{reference.name}"
                )
            )
        foods = sum(len(link.foods) for link in kept.links)
        defaults = sum(1 for link in kept.links if link.default)
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(kept.links)} reference(s) with {foods} food(s) and "
                f"{defaults} default(s) written to {path}."
            )
        )
