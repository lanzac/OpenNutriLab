from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.utils import translation

from opennutrilab.meals.models import Profile
from opennutrilab.users.models import User
from opennutrilab.users.tests.factories import UserFactory

URL = "/needs/"


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


# ----------------------------------------------------------------------------
# The meals page
# ----------------------------------------------------------------------------
MEALS_URL = "/meals/"


@pytest.mark.django_db
def test_the_meals_page_needs_a_signed_in_user(client: Client):
    response = client.get(MEALS_URL)

    assert response.status_code == 302  # noqa: PLR2004
    assert "/accounts/login/" in response["Location"]


@pytest.mark.django_db
def test_the_meals_page_is_the_react_mount_point_with_what_it_needs(
    client: Client, user: User
):
    client.force_login(user)

    response = client.get(MEALS_URL)

    assert response.status_code == 200  # noqa: PLR2004
    html = response.content.decode()
    assert 'id="meals-root"' in html
    assert 'id="meals-props"' in html
    props = response.context["meals_props"]
    assert props["today"] == timezone.localdate().isoformat()
    assert props["needsUrl"] == "/needs/"
    assert props["inventoryUrl"] == reverse("list_products")
    # CSRF_COOKIE_HTTPONLY hides the token from the page's own scripts.
    assert props["csrfToken"]
    assert props["csrfToken"] in html


@pytest.mark.django_db
def test_the_labels_of_the_meals_page_are_translated_by_the_server(
    client: Client, user: User
):
    client.force_login(user)

    with translation.override("fr-fr"):
        response = client.get(MEALS_URL, headers={"accept-language": "fr"})

    props = response.context["meals_props"]
    labels = props["labels"]
    assert props["languageCode"].startswith("fr")
    assert labels["loadError"] == "Les repas n'ont pas pu être chargés."
    assert labels["add"] == "Ajouter"
    assert labels["within"] == "Respecté"
    assert labels["serving"] == "portion"
    assert labels["myNeeds"] == "Mes besoins"
    # Nothing is left in English.
    assert all(isinstance(value, str) and value for value in labels.values())
    assert labels["coverage"] == "Couverture"
    assert labels["proposeDay"] == "Proposer un jour"
    assert labels["useDay"] == "Utiliser ce jour"
    assert labels["proposal_time_limit"].startswith("Le temps est écoulé")
    assert labels["save"] == "Sauvegarder"


@pytest.mark.django_db
def test_the_meals_are_in_the_menu(client: Client, user: User):
    client.force_login(user)

    html = client.get(MEALS_URL).content.decode()

    assert 'href="/meals/"' in html
