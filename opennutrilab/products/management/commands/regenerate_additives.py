from datetime import UTC
from datetime import datetime
from typing import Any
from typing import override

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser
from django.db import transaction

from opennutrilab.products.services.additive_sources import AdditiveSourceError
from opennutrilab.products.services.additive_sources import additives_of_union_list
from opennutrilab.products.services.additive_sources import build_dataset
from opennutrilab.products.services.additive_sources import fetch_french_page
from opennutrilab.products.services.additive_sources import fetch_union_list
from opennutrilab.products.services.additive_sources import french_names_of_page
from opennutrilab.products.services.additive_sync import DatasetEntry
from opennutrilab.products.services.additive_sync import clear_untouched
from opennutrilab.products.services.additive_sync import read_dataset
from opennutrilab.products.services.additive_sync import sync_additives
from opennutrilab.products.services.additive_sync import write_dataset


class Command(BaseCommand):
    help = (
        "Rebuild the table of additives. It is loaded by a migration from the "
        "dataset (products/data/additives.json), so this is only for when the "
        "European Commission's list has changed: it reads that list and Wikipedia's "
        "French names, writes the dataset again and loads it into the table: what an "
        "import made and nothing has touched (still to review, used by no "
        "ingredient, no nutrient, no source food) is rebuilt from it, and what a "
        "person has worked on is only completed. --offline only loads the dataset "
        "as it is. --dry-run says what would change and keeps nothing, neither the "
        "file nor the table."
    )

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--offline",
            action="store_true",
            help="Read nothing: load the dataset of the repository into the table.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Say what would change, and keep nothing.",
        )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        dry_run: bool = options["dry_run"]
        previous = _previous_entries()
        left_out: list[str] = []
        if options["offline"]:
            dataset, entries = read_dataset()
        else:
            dataset, entries, left_out = self._rebuild()

        with transaction.atomic():
            # What an import made that nothing has touched goes first, and is loaded
            # again if the dataset has it.
            cleared = clear_untouched()
            report = sync_additives(entries)
            if dry_run:
                transaction.set_rollback(True)
        if not (options["offline"] or dry_run):
            write_dataset(dataset)

        for line in left_out:
            self.stdout.write(self.style.WARNING(f"Left out, {line}"))
        self._say_what_changed(previous, entries)
        summary = (
            f"{len(entries)} additives in the dataset: {report.created} created, "
            f"{report.completed} completed, {report.unchanged} already complete, "
            f"{cleared} untouched ones rebuilt, {report.shared_names} name(s) left "
            "off an additive that shares it."
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Dry run, nothing kept. {summary}" if dry_run else summary
            )
        )

    def _rebuild(self) -> tuple[dict[str, Any], list[DatasetEntry], list[str]]:
        try:
            union, left_out = additives_of_union_list(fetch_union_list())
            page, revision = fetch_french_page()
        except AdditiveSourceError as e:
            raise CommandError(str(e)) from e
        dataset = build_dataset(
            union,
            french_names_of_page(page),
            generated=datetime.now(tz=UTC).date().isoformat(),
            wikipedia_revision=revision,
        )
        entries = [
            DatasetEntry(a["code"], a["name_en"], a["name_fr"], a["ref"])
            for a in dataset["additives"]
        ]
        return dataset, entries, left_out

    def _say_what_changed(
        self, previous: list[DatasetEntry], entries: list[DatasetEntry]
    ) -> None:
        """What the rebuilt dataset has that the one of the repository did not."""
        before = {e.code: e for e in previous}
        now = {e.code: e for e in entries}
        added = sorted(set(now) - set(before))
        removed = sorted(set(before) - set(now))
        renamed = sorted(
            c for c in set(now) & set(before) if now[c][1:3] != before[c][1:3]
        )
        no_french = sorted(c for c, e in now.items() if not e.name_fr)
        if added:
            self.stdout.write(f"New in the list: {', '.join(added)}")
        if removed:
            self.stdout.write(f"No longer in the list: {', '.join(removed)}")
        if renamed:
            self.stdout.write(f"Names that changed: {', '.join(renamed)}")
        if no_french:
            self.stdout.write(
                f"{len(no_french)} additive(s) without a French name: "
                f"{', '.join(no_french)}"
            )


def _previous_entries() -> list[DatasetEntry]:
    try:
        return read_dataset()[1]
    except (OSError, ValueError, KeyError):
        return []
