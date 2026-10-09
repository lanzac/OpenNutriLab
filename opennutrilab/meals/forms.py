from typing import Any

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Column
from crispy_forms.layout import Field
from crispy_forms.layout import Fieldset
from crispy_forms.layout import Layout
from crispy_forms.layout import Row
from crispy_forms.layout import Submit
from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from opennutrilab.meals.models import Profile
from opennutrilab.meals.services.needs import ADULT_AGE


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields: list[str] = [
            "sex",
            "birth_year",
            "height",
            "weight",
            "activity_level",
            "high_iron_losses",
            "dha_epa_ratio",
            "omega3_omega6_ratio",
            "ratio_tolerance",
        ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = "profile-form"
        self.helper.layout = Layout(
            Fieldset(
                _("Who the meals are for"),
                Row(
                    Column(Field("sex"), css_class="col-md-4"),
                    Column(Field("birth_year"), css_class="col-md-4"),
                ),
                Row(
                    Column(Field("height"), css_class="col-md-4"),
                    Column(Field("weight"), css_class="col-md-4"),
                    Column(Field("activity_level"), css_class="col-md-4"),
                ),
                Field("high_iron_losses"),
            ),
            Fieldset(
                _("Your targets"),
                Row(
                    Column(Field("dha_epa_ratio"), css_class="col-md-4"),
                    Column(Field("omega3_omega6_ratio"), css_class="col-md-4"),
                    Column(Field("ratio_tolerance"), css_class="col-md-4"),
                ),
            ),
            Submit("save", _("Save"), css_class="btn-primary mt-2"),
        )

    def clean_birth_year(self) -> int:
        year: int = self.cleaned_data["birth_year"]
        if timezone.localdate().year - year < ADULT_AGE:
            raise forms.ValidationError(
                _("The references kept are for adults, from %(age)s.")
                % {"age": ADULT_AGE}
            )
        return year
