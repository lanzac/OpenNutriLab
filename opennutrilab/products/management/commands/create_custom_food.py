import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from typing import override

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser
from django.db import transaction

from opennutrilab.products.models import Nutrient
from opennutrilab.products.services.custom_foods import MANUAL_SOURCE_CODE
from opennutrilab.products.services.custom_foods import CustomFood
from opennutrilab.products.services.custom_foods import CustomFoodError
from opennutrilab.products.services.custom_foods import Value
from opennutrilab.products.services.custom_foods import create_custom_food
from opennutrilab.products.services.custom_foods import parse_spec


class Command(BaseCommand):
    help = (
        "Make foods of the source Manual from JSON specs, for reference "
        "ingredients that no source has a food for, and link them to the "
        "references the specs name. A spec says which source foods a food is worked "
        "out from (proxies), how they are mixed and brought to a water content, and "
        "the nutrients given by hand; the figures are intervals graded D. See "
        "services/custom_foods.py. Given a folder, it takes every spec in it, which "
        "is how the foods of products/data/custom_foods are made again after a "
        "reset (once the references they name exist). --dry-run keeps nothing; "
        "--replace writes again a food of that code."
    )

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "specs",
            type=Path,
            nargs="+",
            help="JSON files of specs, or folders holding them (their *.json).",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Replace the food of that code if there is one (refused otherwise).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Say what would be made, and keep nothing.",
        )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        files = [f for path in options["specs"] for f in _spec_files(path)]
        dry_run: bool = options["dry_run"]
        made: list[CustomFood] = []
        failures: list[str] = []

        with transaction.atomic():
            for spec_file in files:
                if len(files) > 1:
                    self.stdout.write(self.style.MIGRATE_HEADING(str(spec_file)))
                try:
                    food = _make(spec_file, replace=options["replace"])
                except CommandError as e:
                    failures.append(str(e))
                    self.stdout.write(self.style.ERROR(str(e)))
                    continue
                made.append(food)
                self._report(food)
            if dry_run:
                transaction.set_rollback(True)

        created = sum(1 for food in made if food.created)
        summary = (
            f"{created} food(s) of {MANUAL_SOURCE_CODE} made, "
            f"{len(made) - created} replaced, "
            f"{sum(len(food.linked) for food in made)} link(s) to references."
        )
        if failures:
            msg = f"{len(failures)} spec(s) not made, {summary}\n" + "\n".join(failures)
            raise CommandError(msg)
        self.stdout.write(
            self.style.SUCCESS(
                f"Dry run, nothing kept. {summary}" if dry_run else summary
            )
        )

    def _report(self, made: CustomFood) -> None:
        worked = made.worked_out
        self.stdout.write(made.food.name_fr or made.food.name_en)
        if made.food.name_fr and made.food.name_en:
            self.stdout.write(made.food.name_en)
        units = dict(Nutrient.objects.values_list("code", "unit"))
        shown = [
            n for n in Nutrient.objects.filter(on_label=True) if n.code in worked.values
        ]
        for nutrient in shown:
            self.stdout.write(
                f"  {nutrient.code:<14}{_figure(worked.values[nutrient.code])} "
                f"{units[nutrient.code]}"
            )
        others = len(worked.values) - len(shown)
        if others:
            self.stdout.write(f"  and {others} more nutrient(s)")
        if worked.left_out:
            self.stdout.write(
                self.style.WARNING(
                    f"Left out ({len(worked.left_out)}): "
                    + "; ".join(f"{c} ({why})" for c, why in worked.left_out.items())
                )
            )
        for warning in worked.warnings:
            self.stdout.write(self.style.WARNING(f"Warning: {warning}"))
        for reference in made.linked:
            drawing = (
                f", which already draws on {reference.other_foods} other food(s)"
                if reference.other_foods
                else ""
            )
            self.stdout.write(
                f"Linked to {reference.reference.pk}: {reference.reference.name}"
                f" ({reference.reference.status}){drawing}"
            )


def _figure(value: Value) -> str:
    """An amount with its range, `12.5 [10.6 - 14.4]`, or what a source says."""
    if value.amount is None:
        return "traces"
    amount = _plain(value.amount)
    if value.low is None or value.high is None:
        return f"< {amount}"
    return f"{amount} [{_plain(value.low)} - {_plain(value.high)}]"


def _plain(number: Decimal) -> str:
    """Three significant digits: the figures are estimates."""
    if number == 0:
        return "0"
    rounded = number.quantize(Decimal(1).scaleb(number.adjusted() - 2))
    return f"{rounded.normalize():f}"


def _spec_files(path: Path) -> list[Path]:
    """The spec a path is, or the specs of a folder, by name."""
    if not path.is_dir():
        return [path]
    files = sorted(path.glob("*.json"))
    if not files:
        msg = f"No spec (*.json) in {path}."
        raise CommandError(msg)
    return files


def _make(spec_file: Path, *, replace: bool) -> CustomFood:
    """One spec made into a food, or a CommandError that says which file."""
    try:
        spec = parse_spec(json.loads(spec_file.read_text(encoding="utf-8")))
        with transaction.atomic():
            return create_custom_food(spec, replace=replace)
    except OSError as e:
        msg = f"Cannot read {spec_file}: {e}"
        raise CommandError(msg) from e
    except (ValueError, CustomFoodError) as e:
        msg = f"{spec_file}: {e}"
        raise CommandError(msg) from e
