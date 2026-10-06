"""
Products, their ingredients, and the nutrient data behind them.

- Nutrient: the one catalogue every amount below refers to, each nutrient
  with its unit. All amounts are per 100 g, in that unit.
- Product and ProductNutrient: what a product's nutrition label declares.
- Ingredient: a product's ingredient tree, as its label lists it. Each one is
  a reference ingredient or a preparation, and has no name of its own.
- IngredientTaxon: OpenFoodFacts' ingredient taxonomy, a dictionary of the
  English and French names of what a label names, with a CIQUAL hint. It gives
  a wording its English name, and proposes foods. Nothing links to it.
- Source, SourceFood and SourceFoodNutrient: composition data exactly as a
  food composition table publishes it (CIQUAL first), with its qualifiers
  and confidence grades.
- ReferenceIngredient: a curated true ingredient ("carotte crue") drawing on any
  number of source foods. Product ingredients link to it.
- Preparation: what is made of several ingredients ("mozzarella", "gnocchi"),
  which a reference must not be. It points to the references it is made of, and
  may draw on source foods too. Product ingredients link to it as well.
"""

from collections.abc import Iterable
from typing import TYPE_CHECKING
from typing import Any
from typing import override

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from .fields import EAN13Field

if TYPE_CHECKING:
    from django.db.models.manager import RelatedManager


class Nutrient(models.Model):
    parent_id: str | None

    class Unit(models.TextChoices):
        KILOJOULE = "kJ", "kJ"
        GRAM = "g", "g"
        MILLIGRAM = "mg", "mg"
        MICROGRAM = "µg", "µg"

    class Group(models.TextChoices):
        ENERGY = "energy", _("Energy")
        MACRONUTRIENT = "macronutrient", _("Macronutrient")
        MINERAL = "mineral", _("Mineral")
        VITAMIN = "vitamin", _("Vitamin")
        OTHER = "other", _("Other")

    code = models.SlugField(primary_key=True, max_length=50)
    name_en = models.CharField(max_length=100)
    name_fr = models.CharField(max_length=100)
    unit = models.CharField(max_length=3, choices=Unit.choices)
    group = models.CharField(max_length=20, choices=Group.choices)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        help_text=_("The nutrient this one is part of: sugars are carbohydrates."),
    )
    on_label = models.BooleanField(
        default=False,
        help_text=_("Part of the nutrition declaration the product form asks for."),
    )
    display_order = models.PositiveSmallIntegerField(default=0)
    ciqual_code = models.CharField(
        max_length=10,
        unique=True,
        null=True,
        blank=True,
        help_text=_("Code of the matching constituent in the CIQUAL table."),
    )
    off_key = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        help_text=_("OpenFoodFacts nutriment key, e.g. saturated-fat."),
    )

    if TYPE_CHECKING:
        components: RelatedManager["NutrientComponent"]

    class Meta:
        ordering = ["display_order", "code"]

    @override
    def __str__(self) -> str:
        return f"{self.name} ({self.unit})"

    @property
    def name(self) -> str:
        """The name in the language being served."""
        return self.name_fr if (get_language() or "").startswith("fr") else self.name_en


class NutrientComponent(models.Model):
    """
    One term of a derived nutrient: derived = sum of factor x component.

    The factor carries any unit conversion between the two (sodium in mg to
    salt in g, for instance, is x 0.0025), and is positive, so that a derived
    amount grows with each component and its low and high ends can be derived
    from the components' own. Which terms are used is in
    services.derived_nutrients.
    """

    derived_id: str
    component_id: str

    derived = models.ForeignKey(
        Nutrient, on_delete=models.CASCADE, related_name="components"
    )
    component = models.ForeignKey(Nutrient, on_delete=models.PROTECT, related_name="+")
    factor = models.DecimalField(max_digits=12, decimal_places=6)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["derived", "component"], name="unique_nutrient_component"
            ),
            # django-stubs still types `check`, which Django 5.1 renamed.
            models.CheckConstraint(  # pyright: ignore[reportCallIssue]
                condition=models.Q(factor__gt=0),  # pyright: ignore[reportCallIssue]
                name="nutrient_component_factor_is_positive",
            ),
        ]

    @override
    def __str__(self) -> str:
        return f"{self.derived_id} = {self.factor} x {self.component_id}"


class Product(models.Model):
    barcode = EAN13Field(primary_key=True)
    name = models.CharField(max_length=100)
    image = models.ImageField(upload_to="images/products/", null=True, blank=True)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    group_level_1 = models.CharField(max_length=100, blank=True)
    group_level_2 = models.CharField(max_length=100, blank=True)
    # The list of ingredients as the label prints it, which the ingredients were
    # read from (see services.label_parser): kept so that a badly read list can be
    # told from a badly written one. Set when the ingredients come from
    # OpenFoodFacts and never edited, so it can be older than the text OFF has now.
    ingredients_text = models.TextField(
        blank=True,
        default="",
        help_text=_("The ingredient list as the label prints it."),
    )

    if TYPE_CHECKING:
        declared_nutrients: RelatedManager["ProductNutrient"]
        ingredients: RelatedManager["Ingredient"]

    @override
    def __str__(self) -> str:
        return self.name.replace("_", " ").title()


class ProductNutrient(models.Model):
    """
    A value from the product's nutrition label.

    Declared values are the reference for the product, and what amounts
    computed from its ingredients are checked against.
    """

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="declared_nutrients"
    )
    nutrient = models.ForeignKey(Nutrient, on_delete=models.PROTECT, related_name="+")
    # Per 100 g, in the nutrient's unit.
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        validators=[MinValueValidator(0, message=_("Amount cannot be negative"))],
    )

    class Meta:
        ordering = ["nutrient__display_order", "nutrient__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "nutrient"], name="unique_declared_nutrient"
            ),
        ]

    @override
    def __str__(self) -> str:
        return f"{self.product}: {self.amount} {self.nutrient}"


class Ingredient(models.Model):
    """
    An ingredient of a product, which is a reference ingredient or a preparation.

    It has no name and keeps nothing OpenFoodFacts says about it: the name is
    that of the one it is, and what OFF gave only served to find or create it
    (see services.reference_services). A preparation is what the label says is
    made of several ingredients: it has the ingredients the label lists in it as
    its children.
    """

    id: int
    parent_id: int | None
    reference_id: int | None
    preparation_id: int | None

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="ingredients"
    )
    # Sub-ingredients: "Dattes 7% (dattes, farine de riz)" is one ingredient
    # with two children.
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="sub_ingredients",
    )
    # One of the two is set, and protected: what is in use cannot be deleted. An
    # ingredient no reference or preparation has the name of gets a reference
    # created, to review, which the curator may turn into a preparation.
    reference: "models.ForeignKey[ReferenceIngredient | None]" = models.ForeignKey(
        "ReferenceIngredient",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="usages",
    )
    preparation: "models.ForeignKey[Preparation | None]" = models.ForeignKey(
        "Preparation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="usages",
    )
    # Declared, never estimated: the OpenFoodFacts import keeps a percentage
    # only if the label's text says it, and estimates are computed on demand,
    # not stored here. A declared figure is rounded to its last digit (33 is
    # 32.5-33.5, 1.4 is 1.35-1.45): that margin is part of the value.
    percentage = models.DecimalField(
        null=True,
        blank=True,
        max_digits=5,
        decimal_places=2,
        validators=[
            MinValueValidator(0, message=_("Percentage cannot be negative")),
            MaxValueValidator(100, message=_("Percentage too large")),
        ],
        help_text=_("Share of the product, as declared on the label."),
    )

    if TYPE_CHECKING:
        sub_ingredients: RelatedManager["Ingredient"]

    class Meta:
        # The order the label lists them in, which is the order they are
        # created in.
        ordering = ["id"]
        constraints = [
            # A null reference or preparation is never equal to another, so each
            # pair of constraints only bears on the rows that have one.
            models.UniqueConstraint(
                fields=["product", "parent", "reference"],
                name="unique_ingredient_per_product_parent",
            ),
            models.UniqueConstraint(
                fields=["product", "reference"],
                condition=models.Q(parent__isnull=True),
                name="unique_root_ingredient_per_product",
            ),
            models.UniqueConstraint(
                fields=["product", "parent", "preparation"],
                name="unique_preparation_per_product_parent",
            ),
            models.UniqueConstraint(
                fields=["product", "preparation"],
                condition=models.Q(parent__isnull=True),
                name="unique_root_preparation_per_product",
            ),
            # django-stubs still types `check`, which Django 5.1 renamed.
            models.CheckConstraint(  # pyright: ignore[reportCallIssue]
                condition=(  # pyright: ignore[reportCallIssue]
                    models.Q(reference__isnull=False, preparation__isnull=True)
                    | models.Q(reference__isnull=True, preparation__isnull=False)
                ),
                name="ingredient_is_a_reference_or_a_preparation",
                violation_error_message=_(
                    "An ingredient is a reference or a preparation, not both."
                ),
            ),
        ]

    @override
    def __str__(self) -> str:
        return str(self.item)

    @property
    def item(self) -> "ReferenceIngredient | Preparation":
        """The reference or the preparation this ingredient is."""
        item = self.reference or self.preparation
        assert item is not None  # The constraint says one of them is set.
        return item


class IngredientTaxon(models.Model):
    """
    An entry of OpenFoodFacts' ingredient taxonomy, e.g. `en:oat-flakes`.

    A dictionary: the English and French names of what a label names. An
    ingredient is read from the label's text, not from OFF's own parsing of it,
    and this is only where a wording is given its English name (and a reference
    created for it its other name) when the taxonomy has it. Loaded by `manage.py
    import_off_taxonomy`.

    Nothing links to it. It is OFF's data, which does not always match what is
    curated (an id OFF has renamed since, an ingredient the taxonomy does not
    know), so the reference ingredients stay apart from it. The CIQUAL codes it
    gives are hints for whoever curates, and are not trusted: some are out of
    date (9311 for oat flakes, which CIQUAL 2025 numbers 32140), and the same
    code is given to entries that differ.
    """

    off_id = models.CharField(max_length=255, unique=True)
    # Blank when the taxonomy has no name in that language: an ingredient OFF
    # does not know in English has an id prefixed by the label's language,
    # e.g. `fr:oignon-et-ail-en-poudre`.
    name_en = models.CharField(max_length=255, blank=True)
    name_fr = models.CharField(max_length=255, blank=True)
    # The CIQUAL food OFF says the ingredient is, and the one it stands for when
    # there is none that is the ingredient itself. Either may be blank.
    ciqual_food_code = models.CharField(max_length=10, blank=True)
    ciqual_proxy_food_code = models.CharField(max_length=10, blank=True)

    class Meta:
        ordering = ["off_id"]

    @override
    def __str__(self) -> str:
        return f"{self.off_id} ({self.name_en or self.name_fr})"

    @classmethod
    def display_names(cls, off_ids: Iterable[str]) -> dict[str, str]:
        """
        French names to show for imported ingredients, by OFF id.

        An imported ingredient is named in English, so only French has
        anything to replace it with: the taxonomy's French names while French
        is being served (as Nutrient.name does), and nothing, without a query,
        in any other language. An id the taxonomy does not know, or has no
        French name for, is absent: the imported name is all there is.
        """
        ids = {off_id for off_id in off_ids if off_id}
        if not ids or not (get_language() or "").startswith("fr"):
            return {}
        return dict(
            cls.objects.filter(off_id__in=ids)
            .exclude(name_fr="")
            .values_list("off_id", "name_fr")
        )


class Source(models.Model):
    """A dataset composition data comes from, e.g. the CIQUAL 2020 table."""

    code = models.SlugField(unique=True, max_length=50)
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=50, blank=True)
    url = models.URLField(blank=True)
    attribution = models.TextField(
        blank=True,
        help_text=_("What the licence requires to be shown wherever its data is used."),
    )

    @override
    def __str__(self) -> str:
        return f"{self.name} {self.version}".strip()


class SourceFood(models.Model):
    """One food as a source publishes it, e.g. CIQUAL 20009 "Carotte, crue"."""

    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="foods")
    code = models.CharField(
        max_length=50, help_text=_("The food's identifier in its source.")
    )
    name_fr = models.CharField(max_length=255, blank=True)
    name_en = models.CharField(max_length=255, blank=True)
    food_group = models.CharField(max_length=255, blank=True)
    food_subgroup = models.CharField(max_length=255, blank=True)

    if TYPE_CHECKING:
        nutrients: RelatedManager["SourceFoodNutrient"]

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "code"], name="unique_food_per_source"
            ),
        ]

    @override
    def __str__(self) -> str:
        return f"{self.name_fr or self.name_en} ({self.source.code} {self.code})"


class SourceFoodNutrient(models.Model):
    """An amount exactly as its source publishes it."""

    class Qualifier(models.TextChoices):
        EXACT = "exact", _("Exact")
        LESS_THAN = "less_than", _("Below the detection limit")
        TRACES = "traces", _("Traces")

    food_id: int
    nutrient_id: str

    food = models.ForeignKey(
        SourceFood, on_delete=models.CASCADE, related_name="nutrients"
    )
    nutrient = models.ForeignKey(Nutrient, on_delete=models.PROTECT, related_name="+")
    # Per 100 g, in the nutrient's unit, with the digits the source gives (CIQUAL
    # has up to six decimals).
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(0, message=_("Amount cannot be negative"))],
        help_text=_(
            "Empty when the source did not measure it. Below the detection "
            "limit, this is the limit."
        ),
    )
    # The range the source's own data spans, when it gives one.
    minimum = models.DecimalField(
        max_digits=14,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(0, message=_("Amount cannot be negative"))],
        help_text=_("The lowest value the source's data gives, when it says."),
    )
    maximum = models.DecimalField(
        max_digits=14,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(0, message=_("Amount cannot be negative"))],
        help_text=_("The highest value the source's data gives, when it says."),
    )
    qualifier = models.CharField(
        max_length=10, choices=Qualifier.choices, default=Qualifier.EXACT
    )
    confidence = models.CharField(
        max_length=5,
        blank=True,
        help_text=_("The source's own grade, e.g. CIQUAL's A (best) to D."),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["food", "nutrient"], name="unique_nutrient_per_source_food"
            ),
        ]

    @override
    def __str__(self) -> str:
        return f"{self.food}: {self.amount} {self.nutrient}"


_HAS_A_NAME = ~models.Q(name_en="") | ~models.Q(name_fr="")
_CURATED_HAS_NAME_EN = ~models.Q(status="curated") | ~models.Q(name_en="")


class CuratedItem(models.Model):
    """
    What a reference ingredient and a preparation have in common: the names, the
    notes for whoever curates them, and a status.

    Each name is unique when filled, whatever its case, in its table and across
    the two (see _name_clashes), so a name leads to one of them at most.
    """

    class Status(models.TextChoices):
        TO_REVIEW = "to_review", _("To review")
        CURATED = "curated", _("Curated")

    name_fr = models.CharField(max_length=255, blank=True)
    name_en = models.CharField(max_length=255, blank=True)
    description = models.TextField(
        blank=True,
        help_text=_("Notes for whoever curates it, such as what it was created from."),
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.TO_REVIEW
    )

    class Meta:
        abstract = True

    @override
    def __str__(self) -> str:
        return self.name

    @property
    def name(self) -> str:
        """The name in the language being served, whichever one is filled."""
        if (get_language() or "").startswith("fr"):
            return self.name_fr or self.name_en
        return self.name_en or self.name_fr


def _name_clashes(
    item: CuratedItem, other: type[models.Model], message: str
) -> dict[str, str]:
    """
    The names of `item` that `other`'s table has too, by field, with `message`.

    The database cannot say that a name is one table's or the other's, so the
    forms and the services ask. A name in a language is compared with the other
    table's names in that language: "raisin" being a grape in French and a dried
    one in English, the same word in two languages is not a clash.
    """
    clashes: dict[str, str] = {}
    for field in ("name_en", "name_fr"):
        name = " ".join(getattr(item, field).split())
        if name and other.objects.alias(key=Lower(field)).filter(key=name.lower()):  # pyright: ignore[reportAttributeAccessIssue]
            clashes[field] = message
    return clashes


class ReferenceIngredient(CuratedItem):
    """
    A curated true ingredient, e.g. "carotte crue": made of nothing else a label
    would list. What is made of several ingredients is a Preparation.

    Its composition is aggregated from the source foods it draws on, so that
    more sources make it more complete and more reliable.

    A product's ingredient is one of these, or a preparation: it is found by its
    name, searched in `name_en` and `name_fr`. A name no reference or preparation
    has creates a reference, to review (see services.reference_services).
    """

    source_foods: "models.ManyToManyField[SourceFood, Any]" = models.ManyToManyField(
        SourceFood, blank=True, related_name="reference_ingredients"
    )

    if TYPE_CHECKING:
        usages: RelatedManager["Ingredient"]
        used_in_preparations: RelatedManager["Preparation"]

    class Meta(CuratedItem.Meta):
        constraints = [
            models.UniqueConstraint(
                Lower("name_en"),
                condition=~models.Q(name_en=""),
                name="unique_reference_name_en",
            ),
            models.UniqueConstraint(
                Lower("name_fr"),
                condition=~models.Q(name_fr=""),
                name="unique_reference_name_fr",
            ),
            # django-stubs still types `check`, which Django 5.1 renamed.
            models.CheckConstraint(  # pyright: ignore[reportCallIssue]
                condition=_HAS_A_NAME,  # pyright: ignore[reportCallIssue]
                name="reference_has_a_name",
            ),
            # The English name is the key: a reference may lack it while it
            # is to review, but not once it is curated.
            models.CheckConstraint(  # pyright: ignore[reportCallIssue]
                condition=_CURATED_HAS_NAME_EN,  # pyright: ignore[reportCallIssue]
                name="curated_reference_has_name_en",
                violation_error_message=_(
                    "A curated reference needs its English name."
                ),
            ),
        ]

    @override
    def clean(self) -> None:
        super().clean()
        if clashes := _name_clashes(
            self, Preparation, str(_("A preparation already has this name."))
        ):
            raise ValidationError({field: [text] for field, text in clashes.items()})


class Preparation(CuratedItem):
    """
    What is made of several ingredients, e.g. "mozzarella" or "gnocchi": a
    product used as an ingredient, which is not an ingredient to be linked to a
    food as milk or salt are.

    It stands between what a label says and the true ingredients. It points to
    the references it is made of, which are its default recipe: used when the
    label does not list its parts, never over those the label does list. It may
    also draw on source foods, whose composition is measured (CIQUAL's
    "Mozzarella"), and which counts at its level, as a reference's does.
    """

    components: "models.ManyToManyField[ReferenceIngredient, Any]" = (
        models.ManyToManyField(
            ReferenceIngredient,
            blank=True,
            related_name="used_in_preparations",
            help_text=_("The ingredients it is made of, when the label lists none."),
        )
    )
    source_foods: "models.ManyToManyField[SourceFood, Any]" = models.ManyToManyField(
        SourceFood, blank=True, related_name="preparations"
    )

    if TYPE_CHECKING:
        usages: RelatedManager["Ingredient"]

    class Meta(CuratedItem.Meta):
        constraints = [
            models.UniqueConstraint(
                Lower("name_en"),
                condition=~models.Q(name_en=""),
                name="unique_preparation_name_en",
            ),
            models.UniqueConstraint(
                Lower("name_fr"),
                condition=~models.Q(name_fr=""),
                name="unique_preparation_name_fr",
            ),
            models.CheckConstraint(  # pyright: ignore[reportCallIssue]
                condition=_HAS_A_NAME,  # pyright: ignore[reportCallIssue]
                name="preparation_has_a_name",
            ),
            models.CheckConstraint(  # pyright: ignore[reportCallIssue]
                condition=_CURATED_HAS_NAME_EN,  # pyright: ignore[reportCallIssue]
                name="curated_preparation_has_name_en",
                violation_error_message=_(
                    "A curated preparation needs its English name."
                ),
            ),
        ]

    @override
    def clean(self) -> None:
        super().clean()
        if clashes := _name_clashes(
            self,
            ReferenceIngredient,
            str(_("A reference ingredient already has this name.")),
        ):
            raise ValidationError({field: [text] for field, text in clashes.items()})
