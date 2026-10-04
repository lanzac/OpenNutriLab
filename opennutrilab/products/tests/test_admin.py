from http import HTTPStatus
from typing import Any

import pytest
from django.http.response import HttpResponse
from django.test import Client
from django.urls import reverse

from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Product
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

REFERENCES = "admin:products_referenceingredient_changelist"
FOODS = "admin:products_sourcefood_changelist"


@pytest.fixture
def admin_client(client: Client) -> Client:
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    return client


def used_by(reference: ReferenceIngredient, *barcodes: str) -> None:
    for barcode in barcodes:
        product, _created = Product.objects.get_or_create(
            barcode=barcode, defaults={"name": barcode}
        )
        Ingredient.objects.create(product=product, reference=reference)


def messages_of(response: HttpResponse) -> list[str]:
    return [str(m) for m in response.context["messages"]]


# ----------------------------------------------------------------------------
# The worklist
# ----------------------------------------------------------------------------
def test_the_references_are_listed_most_used_first_with_their_counts(
    admin_client: Client,
):
    ReferenceIngredient.objects.create(name_en="unused")
    once = ReferenceIngredient.objects.create(name_en="once")
    twice = ReferenceIngredient.objects.create(name_en="twice")
    used_by(twice, "3229820794556", "3017620422003")
    used_by(once, "3229820794556")
    twice.source_foods.add(
        SourceFood.objects.create(
            source=Source.objects.create(code="ciqual-2025", name="Ciqual"), code="1"
        )
    )

    response = admin_client.get(reverse(REFERENCES))

    rows = response.context["cl"].result_list
    assert [r.name_en for r in rows] == ["twice", "once", "unused"]
    assert [(r.usage_count, r.food_count) for r in rows] == [(2, 1), (1, 0), (0, 0)]


def test_the_worklist_filters_references_with_and_without_source_foods(
    admin_client: Client,
):
    bare = ReferenceIngredient.objects.create(name_en="bare")
    fed = ReferenceIngredient.objects.create(name_en="fed")
    fed.source_foods.add(
        SourceFood.objects.create(
            source=Source.objects.create(code="ciqual-2025", name="Ciqual"), code="1"
        )
    )

    def listed(value: str) -> list[ReferenceIngredient]:
        response = admin_client.get(reverse(REFERENCES), {"source_foods": value})
        return list(response.context["cl"].result_list)

    assert listed("without") == [bare]
    assert listed("with") == [fed]


def test_a_reference_is_still_found_by_its_name_from_an_ingredient_form(
    admin_client: Client,
):
    """The ordering by usage must not break the autocomplete the forms use."""
    carrot = ReferenceIngredient.objects.create(name_en="carrot")
    used_by(carrot, "3229820794556")

    response = admin_client.get(
        reverse("admin:autocomplete"),
        {
            "term": "carr",
            "app_label": "products",
            "model_name": "ingredient",
            "field_name": "reference",
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert [r["id"] for r in response.json()["results"]] == [str(carrot.pk)]


# ----------------------------------------------------------------------------
# Marking as curated
# ----------------------------------------------------------------------------
def test_references_are_marked_as_curated_when_they_have_their_english_name(
    admin_client: Client,
):
    ready = ReferenceIngredient.objects.create(name_en="carrot")
    waiting = ReferenceIngredient.objects.create(name_fr="oignon")

    response = admin_client.post(
        reverse(REFERENCES),
        {"action": "mark_curated", "_selected_action": [ready.pk, waiting.pk]},
        follow=True,
    )

    ready.refresh_from_db()
    waiting.refresh_from_db()
    assert ready.status == ReferenceIngredient.Status.CURATED
    assert waiting.status == ReferenceIngredient.Status.TO_REVIEW
    assert any("lack an English name" in m for m in messages_of(response))
    assert any("1 reference(s) marked as curated" in m for m in messages_of(response))


# ----------------------------------------------------------------------------
# Suggestions
# ----------------------------------------------------------------------------
def test_a_references_page_suggests_foods_that_may_fit_it(admin_client: Client):
    ciqual = Source.objects.create(code="ciqual-2025", name="Ciqual")
    raw = SourceFood.objects.create(
        source=ciqual, code="20009", name_fr="Carotte, crue"
    )
    SourceFood.objects.create(source=ciqual, code="20100", name_fr="Chou, cru")
    carrot = ReferenceIngredient.objects.create(name_fr="carotte")

    page = admin_client.get(
        reverse("admin:products_referenceingredient_change", args=[carrot.pk])
    ).content.decode()

    assert "Carotte, crue" in page
    assert "Chou, cru" not in page
    assert reverse("admin:products_sourcefood_change", args=[raw.pk]) in page


def test_the_page_says_so_when_no_food_fits(admin_client: Client):
    odd = ReferenceIngredient.objects.create(name_en="unobtainium")

    page = admin_client.get(
        reverse("admin:products_referenceingredient_change", args=[odd.pk])
    ).content.decode()

    assert "None found by name." in page


def test_the_new_reference_form_has_no_suggestions_and_does_not_fail(
    admin_client: Client,
):
    response = admin_client.get(reverse("admin:products_referenceingredient_add"))

    assert response.status_code == HTTPStatus.OK


# ----------------------------------------------------------------------------
# Creating a reference from foods
# ----------------------------------------------------------------------------
def foods_selected(
    client: Client, foods: list[SourceFood], *, follow: bool = False
) -> Any:
    return client.post(
        reverse(FOODS),
        {"action": "create_reference", "_selected_action": [f.pk for f in foods]},
        follow=follow,
    )


def test_a_reference_is_created_from_the_selected_foods_and_opened(
    admin_client: Client,
):
    ciqual = Source.objects.create(code="ciqual-2025", name="Ciqual")
    foods = [
        SourceFood.objects.create(
            source=ciqual, code=code, name_fr=name_fr, name_en=name_en
        )
        for code, name_fr, name_en in [
            ("20009", "Carotte, crue", "Carrot, raw"),
            ("20010", "Carotte, râpée, crue", "Carrot, grated, raw"),
        ]
    ]

    response = foods_selected(admin_client, foods)

    reference = ReferenceIngredient.objects.get()
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == reverse(
        "admin:products_referenceingredient_change", args=[reference.pk]
    )
    assert set(reference.source_foods.all()) == set(foods)


def test_no_reference_is_created_when_one_has_the_name_and_the_curator_is_told(
    admin_client: Client,
):
    ciqual = Source.objects.create(code="ciqual-2025", name="Ciqual")
    food = SourceFood.objects.create(source=ciqual, code="1", name_en="Carrot, raw")
    ReferenceIngredient.objects.create(name_en="carrot, raw")

    response = foods_selected(admin_client, [food], follow=True)

    assert ReferenceIngredient.objects.count() == 1
    assert any("already has the name" in m for m in messages_of(response))
