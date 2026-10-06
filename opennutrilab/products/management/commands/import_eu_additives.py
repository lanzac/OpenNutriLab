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
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.services.additive_import import EU_SOURCE
from opennutrilab.products.services.additive_import import additives_of_union_list
from opennutrilab.products.services.additive_import import import_additives
from opennutrilab.products.services.additive_import import prune_additives
from opennutrilab.products.services.additive_services import additives_known_as

# The Union list of food additives, as the Food and Feed Information Portal of the
# European Commission serves it to its own page (about 12 MB, with the conditions of
# use of each substance, which are not read).
UNION_LIST_URL = (
    "https://ec.europa.eu/food/food-feed-portal/backend/api/policy-items"
    "?foodDomain=fin&authorisationType=fad_auth"
)


def read_union_list(path: Path | None) -> list[Any]:
    """The Union list, from a local file, or else downloaded from the portal."""
    try:
        if path is None:
            response = requests.get(UNION_LIST_URL, timeout=300, headers=OFF_HEADERS)
            response.raise_for_status()
            data = response.json()
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, requests.RequestException, ValueError) as e:
        msg = f"Could not read the Union list from {path or UNION_LIST_URL}: {e}"
        raise CommandError(msg) from e
    if not isinstance(data, list):
        msg = "Not the Union list of additives: expected a list of policy items."
        raise CommandError(msg)
    return cast("list[Any]", data)


class Command(BaseCommand):
    help = (
        "Fill the table of additives from the European Commission's Union list of "
        "food additives (the substances that have an E number), as additives to "
        "review with no class. Downloads it unless --path is given. An additive "
        "that is there is only completed, never overwritten, so running it again "
        "is safe. --prune also deletes the additives an import of OpenFoodFacts' "
        "list made that the Union list does not have, if nothing has touched them. "
        "--dry-run says what would change and keeps nothing."
    )

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--path",
            type=Path,
            help="A local copy of the list (a JSON file), instead of downloading it.",
        )
        parser.add_argument(
            "--prune",
            action="store_true",
            help="Delete the untouched additives of OpenFoodFacts' list that it lacks.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Say what would change, and keep nothing.",
        )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        imported, left_out = additives_of_union_list(read_union_list(options["path"]))
        with transaction.atomic():
            report = import_additives(imported, source=EU_SOURCE)
            pruned = (
                prune_additives({a.code for a in imported}) if options["prune"] else 0
            )
            known = additives_known_as(list(ReferenceIngredient.objects.all()))
            if options["dry_run"]:
                transaction.set_rollback(True)

        for line in left_out:
            self.stdout.write(self.style.WARNING(f"Left out, {line}"))
        done = (
            f"{report.created} additive(s) created, {report.completed} completed, "
            f"{report.unchanged} already complete; {len(left_out)} substance(s) left "
            f"out, {report.shared_names} name(s) left off an additive that shares it"
            + (
                f"; {pruned} untouched additive(s) of the other list deleted."
                if options["prune"]
                else "."
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Dry run, nothing kept: {done}" if options["dry_run"] else done
            )
        )
        if known:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(known)} reference(s) have the name of an additive: in the "
                    "admin of the references, filter them with 'Known as an additive' "
                    "and use 'Make an additive of the selected references'."
                )
            )
        self.stdout.write(
            "French names are not in this list: import_off_additives completes them."
        )
