from typing import Any
from typing import override

from django.core.management.base import BaseCommand
from django.core.management.base import CommandParser
from django.db.models import Q

from opennutrilab.products.models import Product
from opennutrilab.products.services.stored_estimates import work_out


class Command(BaseCommand):
    help = (
        "Work out and keep the estimate of each product whose kept estimate is "
        "stale or missing, so that the pages that read many products need not: "
        "after an import, or many changes to the references. With --all, every "
        "product's."
    )

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--all",
            action="store_true",
            help="Work out every product's estimate, stale or not.",
        )
        parser.add_argument(
            "--barcode", action="append", help="Only this product (repeatable)."
        )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        products = Product.objects.order_by("barcode")
        if options["barcode"]:
            products = products.filter(barcode__in=options["barcode"])
        if not options["all"]:
            products = products.filter(
                Q(kept_estimate__isnull=True) | Q(kept_estimate__stale=True)
            )

        done = 0
        for product in products:
            estimate = work_out(product)
            done += 1
            self.stdout.write(
                f"{product.barcode} {product.name}: "
                f"{len(estimate.nutrients.all())} nutrient(s)"
            )
        self.stdout.write(self.style.SUCCESS(f"{done} estimate(s) worked out."))
