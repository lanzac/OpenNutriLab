import tempfile
from pathlib import Path
from typing import Any
from typing import override

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser

from opennutrilab.products.services.ciqual_import import CiqualError
from opennutrilab.products.services.ciqual_import import download_ciqual
from opennutrilab.products.services.ciqual_import import import_ciqual


class Command(BaseCommand):
    help = (
        "Load ANSES' CIQUAL food composition table: its foods, with the "
        "values exactly as it publishes them, and the nutrients they need. "
        "Prepared dishes, sauces and stocks are left out. Downloads the "
        "latest release unless --path is given (the composition file is "
        "about 70 MB, so allow several minutes); running it again updates "
        "what changed."
    )

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--path",
            type=Path,
            help=(
                "A directory with the four XML files of a release (alim, "
                "alim_grp, compo and const, each named with its date), "
                "instead of downloading them."
            ),
        )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        path: Path | None = options["path"]

        def say(message: str) -> None:
            self.stdout.write(message)

        try:
            if path is None:
                with tempfile.TemporaryDirectory(prefix="ciqual-") as directory:
                    download_ciqual(Path(directory), say)
                    report = import_ciqual(Path(directory), say)
            else:
                report = import_ciqual(path, say)
        except CiqualError as e:
            raise CommandError(str(e)) from e

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {report.source}: {report.foods} foods "
                f"({report.excluded} left out), {report.values} values, "
                f"{report.nutrients_created} nutrients added, "
                f"{report.derived} derived."
            )
        )
