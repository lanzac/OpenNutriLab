"""
What a user's meals are worked out for.

- Profile: who eats them (sex, age, height, weight, activity), from which their
  needs are worked out (services.needs), and the user's own targets for the
  ratios of fatty acids.
"""

from decimal import Decimal
from typing import override

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Profile(models.Model):
    """A user's nutrition profile: one adult, neither pregnant nor breastfeeding."""

    user_id: int

    class Sex(models.TextChoices):
        MALE = "male", _("Man")
        FEMALE = "female", _("Woman")

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="nutrition_profile",
    )
    sex = models.CharField(_("Sex"), max_length=6, choices=Sex.choices)
    # The year is enough for the age bands of the references, and says less.
    birth_year = models.PositiveSmallIntegerField(
        _("Year of birth"), validators=[MinValueValidator(1900)]
    )
    height = models.DecimalField(
        _("Height (cm)"),
        max_digits=4,
        decimal_places=1,
        validators=[MinValueValidator(100), MaxValueValidator(250)],
    )
    weight = models.DecimalField(
        _("Weight (kg)"),
        max_digits=4,
        decimal_places=1,
        validators=[MinValueValidator(30), MaxValueValidator(300)],
    )
    activity_level = models.DecimalField(
        _("Physical activity level"),
        max_digits=3,
        decimal_places=2,
        default=Decimal("1.6"),
        validators=[MinValueValidator(Decimal("1.2")), MaxValueValidator(Decimal(3))],
        help_text=_(
            "What a day spends, over the basal metabolism. EFSA's levels: 1.4 "
            "sedentary, 1.6 moderately active, 1.8 active, 2.0 very active."
        ),
    )
    high_iron_losses = models.BooleanField(
        _("High menstrual losses"),
        default=False,
        help_text=_("For a woman: the iron reference is then 16 mg instead of 11."),
    )
    # The user's own targets, on top of the references: DHA over EPA, and the
    # omega-3 over the omega-6, each within the tolerance, as a share of it.
    dha_epa_ratio = models.DecimalField(
        _("DHA:EPA target"),
        max_digits=4,
        decimal_places=2,
        default=Decimal(1),
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    omega3_omega6_ratio = models.DecimalField(
        _("Omega-3:omega-6 target"),
        max_digits=4,
        decimal_places=2,
        default=Decimal(1),
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    ratio_tolerance = models.DecimalField(
        _("Tolerance on the ratios"),
        max_digits=3,
        decimal_places=2,
        default=Decimal("0.10"),
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text=_("0.10: within a tenth of the target."),
    )

    @override
    def __str__(self) -> str:
        return f"{self.user} ({self.get_sex_display()}, {self.age} years)"  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]

    @property
    def age(self) -> int:
        """The age this year, which a year of birth gives to a year."""
        return timezone.localdate().year - self.birth_year
