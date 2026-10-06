from typing import Any
from typing import override

from django.core.management.base import BaseCommand
from django.core.management.base import CommandParser
from django.db import transaction

from opennutrilab.products.models import Additive
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import Product
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.services.product_services import reread_ingredients


class Command(BaseCommand):
    help = (
        "Read again the label text stored with each product, and replace its "
        "ingredients with what it says: to apply a new rule of the label parser, "
        "or a new table (additives), to the products that are already there. A "
        "product with no stored text or whose text looks badly read is left as it "
        "is. With --dry-run nothing is kept."
    )

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--language",
            default="fr",
            help=(
                "The language of the labels (default fr): the stored text does not "
                "say, and it decides where the name of what is new is written."
            ),
        )
        parser.add_argument(
            "--barcode", action="append", help="Only this product (repeatable)."
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Say what would change, and keep nothing.",
        )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        products = Product.objects.order_by("barcode")
        if options["barcode"]:
            products = products.filter(barcode__in=options["barcode"])
        dry_run: bool = options["dry_run"]

        with transaction.atomic():
            counts = _counts()
            done = skipped = 0
            for product in products:
                result = reread_ingredients(product, options["language"])
                if result.done:
                    done += 1
                    self.stdout.write(
                        f"{product.barcode} {product.name}: "
                        f"{result.before} -> {result.after} ingredients"
                    )
                    for warning in result.warnings:
                        self.stdout.write(f"  {warning.message()}")
                else:
                    skipped += 1
                    why = (
                        "; ".join(w.message() for w in result.warnings)
                        or "no stored label text"
                    )
                    self.stdout.write(
                        self.style.WARNING(
                            f"{product.barcode} {product.name}: left as it is ({why})"
                        )
                    )
            made = {name: _counts()[name] - before for name, before in counts.items()}
            if dry_run:
                transaction.set_rollback(True)

        summary = (
            f"{done} product(s) read again, {skipped} left as they were; "
            f"{made['references']} reference(s), {made['preparations']} "
            f"preparation(s) and {made['additives']} additive(s) made."
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Dry run, nothing kept: {summary}" if dry_run else summary
            )
        )


def _counts() -> dict[str, int]:
    return {
        "references": ReferenceIngredient.objects.count(),
        "preparations": Preparation.objects.count(),
        "additives": Additive.objects.count(),
    }
