from decimal import Decimal
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.utils import translation

from opennutrilab.meals.models import Profile
from opennutrilab.products.services.ciqual_import import ensure_nutrients
from opennutrilab.products.services.ciqual_import import read_constituents
from opennutrilab.products.services.derived_nutrients import ensure_derivations
from opennutrilab.users.models import User
from opennutrilab.users.tests.factories import UserFactory

CONSTITUENTS_FILE = (
    Path(__file__).parents[2] / "products" / "tests" / "data" / "ciqual_const_2025.xml"
)
URL = "/needs/"


@pytest.fixture
def catalogue(db: None) -> None:
    ensure_nutrients(read_constituents(CONSTITUENTS_FILE))
    ensure_derivations()


def profile_data(**changes: str) -> dict[str, str]:
    data = {
        "sex": "male",
        "birth_year": str(timezone.localdate().year - 31),
        "height": "180",
        "weight": "61",
        "activity_level": "1.7",
        "dha_epa_ratio": "1",
        "omega3_omega6_ratio": "1",
        "ratio_tolerance": "0.10",
    }
    data.update(changes)
    return data


def test_the_page_is_named_by_its_url():
    assert reverse("nutrition_needs") == URL


@pytest.mark.django_db
def test_the_page_needs_a_signed_in_user(client: Client):
    response = client.get(URL)

    assert response.status_code == 302  # noqa: PLR2004
    assert "/accounts/login/" in response["Location"]


@pytest.mark.django_db
def test_without_a_profile_the_page_asks_for_one(client: Client, user: User):
    client.force_login(user)

    response = client.get(URL)

    assert response.status_code == 200  # noqa: PLR2004
    assert response.context["needs"] is None
    assert b'id="profile-form"' in response.content


def test_saving_the_profile_shows_the_needs_it_gives(
    client: Client, user: User, catalogue: None
):
    client.force_login(user)

    response = client.post(URL, profile_data(), follow=True)

    profile = Profile.objects.get(user=user)
    assert (profile.sex, profile.age, profile.weight) == ("male", 31, Decimal(61))
    assert round(response.context["needs"].energy) == 2651  # noqa: PLR2004
    labels = [group["label"] for group in response.context["groups"]]
    assert labels == ["Energy", "Macronutrient", "Vitamin", "Mineral"]
    with translation.override("fr"):
        response = client.get(URL, headers={"accept-language": "fr"})
    assert "Besoins pour une journée".encode() in response.content


def test_a_profile_is_changed_and_stays_the_users_own(
    client: Client, user: User, catalogue: None
):
    other = UserFactory()
    Profile.objects.create(
        user=other,
        sex="female",
        birth_year=1980,
        height=Decimal(160),
        weight=Decimal(55),
    )
    client.force_login(user)
    client.post(URL, profile_data())

    client.post(URL, profile_data(weight="64"))

    assert Profile.objects.get(user=user).weight == Decimal(64)
    assert Profile.objects.get(user=other).weight == Decimal(55)
    assert Profile.objects.count() == 2  # noqa: PLR2004


@pytest.mark.django_db
def test_a_person_under_eighteen_is_refused(client: Client, user: User):
    client.force_login(user)
    young = str(timezone.localdate().year - 15)

    response = client.post(URL, profile_data(birth_year=young))

    assert response.status_code == 200  # noqa: PLR2004
    assert "birth_year" in response.context["form"].errors
    assert not Profile.objects.exists()
