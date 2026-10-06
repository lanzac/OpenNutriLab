import re
from decimal import Decimal
from http import HTTPStatus
from typing import Any

import pytest
from django.contrib.auth.models import Permission
from django.http.response import HttpResponse
from django.test import Client
from django.urls import reverse

from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import IngredientTaxon
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import Product
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.models import SourceFoodNutrient
from opennutrilab.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

REFERENCES = "admin:products_referenceingredient_changelist"
PREPARATIONS = "admin:products_preparation_changelist"
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


# ----------------------------------------------------------------------------
# Proposing foods for references
# ----------------------------------------------------------------------------
def foods_proposed(client: Client, references: list[ReferenceIngredient], **extra: Any):
    return client.post(
        reverse(REFERENCES),
        {
            "action": "propose_foods",
            "_selected_action": [r.pk for r in references],
            **extra,
        },
    )


@pytest.fixture
def catalogue() -> dict[str, Any]:
    ciqual = Source.objects.create(code="ciqual-2025", name="Ciqual")
    cassis = SourceFood.objects.create(
        source=ciqual, code="13007", name_fr="Cassis, cru", name_en="Blackcurrant, raw"
    )
    soja = SourceFood.objects.create(
        source=ciqual, code="20901", name_fr="Soja, graine entière"
    )
    return {
        "cassis_food": cassis,
        "soja_food": soja,
        "cassis": ReferenceIngredient.objects.create(
            name_en="blackcurrant", name_fr="cassis"
        ),
        "soya": ReferenceIngredient.objects.create(name_en="soya", name_fr="soja"),
    }


def ticked(page: str, name: str) -> bool:
    match = re.search(rf'<input type="checkbox"\s+name="{name}"([^>]*)>', page)
    assert match, f"no checkbox {name}"
    return "checked" in match.group(1)


def test_the_proposals_are_shown_and_nothing_is_linked_yet(
    admin_client: Client, catalogue: dict[str, Any]
):
    IngredientTaxon.objects.create(
        off_id="en:blackcurrant",
        name_en="blackcurrant",
        name_fr="cassis",
        ciqual_food_code="13007",
    )
    cassis, soya = catalogue["cassis"], catalogue["soya"]

    response = foods_proposed(admin_client, [cassis, soya])

    page = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "Cassis, cru" in page
    assert "OpenFoodFacts gives this CIQUAL code" in page
    # The name and OpenFoodFacts agree for one, so it is ticked; the other, with
    # a single signal, is not.
    assert ticked(page, f"link_{cassis.pk}")
    assert not ticked(page, f"link_{soya.pk}")
    assert not cassis.source_foods.exists()
    assert not soya.source_foods.exists()


def test_a_reference_that_already_has_foods_is_not_proposed_again(
    admin_client: Client, catalogue: dict[str, Any]
):
    cassis, soya = catalogue["cassis"], catalogue["soya"]
    cassis.source_foods.add(catalogue["cassis_food"])

    page = foods_proposed(admin_client, [cassis, soya]).content.decode()

    assert f"link_{soya.pk}" in page
    assert f"link_{cassis.pk}" not in page


def test_references_that_all_have_foods_get_a_message_and_no_page(
    admin_client: Client, catalogue: dict[str, Any]
):
    catalogue["cassis"].source_foods.add(catalogue["cassis_food"])

    response = admin_client.post(
        reverse(REFERENCES),
        {
            "action": "propose_foods",
            "_selected_action": [catalogue["cassis"].pk],
        },
        follow=True,
    )

    assert any("already have source foods" in m for m in messages_of(response))


def apply_proposals(
    client: Client, references: list[ReferenceIngredient], **extra: Any
) -> HttpResponse:
    return client.post(
        reverse(REFERENCES),
        {
            "action": "propose_foods",
            "apply": "Link",
            "_selected_action": [r.pk for r in references],
            **extra,
        },
        follow=True,
    )


def test_only_the_ticked_references_are_linked_each_to_the_chosen_food(
    admin_client: Client, catalogue: dict[str, Any]
):
    cassis, soya = catalogue["cassis"], catalogue["soya"]

    response = apply_proposals(
        admin_client,
        [cassis, soya],
        **{
            f"link_{cassis.pk}": "on",
            f"choice_{cassis.pk}": catalogue["cassis_food"].pk,
            f"choice_{soya.pk}": catalogue["soja_food"].pk,  # not ticked
        },
    )

    assert list(cassis.source_foods.all()) == [catalogue["cassis_food"]]
    assert not soya.source_foods.exists()
    assert any("1 reference(s) linked" in m for m in messages_of(response))


def test_linked_references_are_marked_as_curated_when_asked_and_able(
    admin_client: Client, catalogue: dict[str, Any]
):
    cassis, soya = catalogue["cassis"], catalogue["soya"]
    nameless = ReferenceIngredient.objects.create(name_fr="oignon")

    apply_proposals(
        admin_client,
        [cassis, soya, nameless],
        mark_curated="on",
        **{
            f"link_{cassis.pk}": "on",
            f"choice_{cassis.pk}": catalogue["cassis_food"].pk,
            f"link_{nameless.pk}": "on",
            f"choice_{nameless.pk}": catalogue["soja_food"].pk,
        },
    )

    for reference in (cassis, soya, nameless):
        reference.refresh_from_db()
    assert cassis.status == ReferenceIngredient.Status.CURATED
    # Linked, but without its English name it cannot be curated yet.
    assert nameless.source_foods.count() == 1
    assert nameless.status == ReferenceIngredient.Status.TO_REVIEW
    assert soya.status == ReferenceIngredient.Status.TO_REVIEW


def test_references_stay_to_review_when_marking_is_not_asked(
    admin_client: Client, catalogue: dict[str, Any]
):
    cassis = catalogue["cassis"]

    apply_proposals(
        admin_client,
        [cassis],
        **{
            f"link_{cassis.pk}": "on",
            f"choice_{cassis.pk}": catalogue["cassis_food"].pk,
        },
    )

    cassis.refresh_from_db()
    assert cassis.source_foods.count() == 1
    assert cassis.status == ReferenceIngredient.Status.TO_REVIEW


@pytest.mark.parametrize("choice", ["", "none", "999999999", "1; DROP TABLE"])
def test_a_choice_that_is_no_food_links_nothing(
    admin_client: Client, catalogue: dict[str, Any], choice: str
):
    cassis = catalogue["cassis"]

    apply_proposals(
        admin_client,
        [cassis],
        **{f"link_{cassis.pk}": "on", f"choice_{cassis.pk}": choice},
    )

    assert not cassis.source_foods.exists()


def test_proposing_needs_the_permission_to_change_references(
    client: Client, catalogue: dict[str, Any]
):
    viewer = UserFactory(is_staff=True)
    viewer.user_permissions.add(
        Permission.objects.get(codename="view_referenceingredient")
    )
    client.force_login(viewer)
    cassis = catalogue["cassis"]

    apply_proposals(
        client,
        [cassis],
        **{
            f"link_{cassis.pk}": "on",
            f"choice_{cassis.pk}": catalogue["cassis_food"].pk,
        },
    )

    assert not cassis.source_foods.exists()


# ----------------------------------------------------------------------------
# The composition of a reference
# ----------------------------------------------------------------------------
def test_a_references_page_shows_what_its_foods_say_together(admin_client: Client):
    ciqual = Source.objects.create(code="ciqual-2025", name="Ciqual")
    carrot = SourceFood.objects.create(source=ciqual, code="20009", name_fr="Carotte")
    vitamin_c = Nutrient.objects.get(code="fat")  # a label nutrient, in the catalogue
    SourceFoodNutrient.objects.create(
        food=carrot,
        nutrient=vitamin_c,
        amount=Decimal("9.3"),
        minimum=Decimal("7.1"),
        maximum=Decimal("11.9"),
        confidence="B",
    )
    reference = ReferenceIngredient.objects.create(name_en="carrot")
    reference.source_foods.add(carrot)

    page = admin_client.get(
        reverse("admin:products_referenceingredient_change", args=[reference.pk])
    ).content.decode()

    assert "<td>Fat</td>" in page
    assert "<td>9.3 g</td>" in page
    assert "<td>7.1 \u2013 11.9</td>" in page
    assert "<td>B</td>" in page
    assert "Carotte (ciqual-2025 20009)" in page


def test_the_composition_credits_the_sources_it_shows_data_from(admin_client: Client):
    credited = Source.objects.create(
        code="ciqual-2025", name="Ciqual", attribution="Anses. Table Ciqual 2025."
    )
    uncredited = Source.objects.create(code="manual", name="Manual")
    reference = ReferenceIngredient.objects.create(name_en="carrot")
    for source, code in ((credited, "20009"), (uncredited, "m1")):
        food = SourceFood.objects.create(source=source, code=code)
        SourceFoodNutrient.objects.create(
            food=food,
            nutrient=Nutrient.objects.get(code="fat"),
            amount=Decimal("9.3"),
            confidence="B",
        )
        reference.source_foods.add(food)

    page = admin_client.get(
        reverse("admin:products_referenceingredient_change", args=[reference.pk])
    ).content.decode()

    # Once, and a source with no attribution to give adds nothing.
    assert page.count("<p>Anses. Table Ciqual 2025.</p>") == 1
    assert "<p></p>" not in page


def test_a_reference_with_no_value_says_so_and_the_add_form_does_not_fail(
    admin_client: Client,
):
    bare = ReferenceIngredient.objects.create(name_en="bare")

    page = admin_client.get(
        reverse("admin:products_referenceingredient_change", args=[bare.pk])
    ).content.decode()

    assert "No composition" in page
    assert (
        admin_client.get(reverse("admin:products_referenceingredient_add")).status_code
        == HTTPStatus.OK
    )


# ----------------------------------------------------------------------------
# Preparations
# ----------------------------------------------------------------------------
def prepared_for(preparation: Preparation, *barcodes: str) -> None:
    for barcode in barcodes:
        product, _created = Product.objects.get_or_create(
            barcode=barcode, defaults={"name": barcode}
        )
        Ingredient.objects.create(product=product, preparation=preparation)


def test_the_preparations_are_listed_most_used_first_with_their_counts(
    admin_client: Client,
):
    Preparation.objects.create(name_en="unused")
    once = Preparation.objects.create(name_en="once")
    twice = Preparation.objects.create(name_en="twice")
    prepared_for(twice, "3229820794556", "3017620422003")
    prepared_for(once, "3229820794556")
    twice.components.set(
        [ReferenceIngredient.objects.create(name_en=n) for n in ("milk", "salt")]
    )
    twice.source_foods.add(
        SourceFood.objects.create(
            source=Source.objects.create(code="ciqual-2025", name="Ciqual"), code="1"
        )
    )

    response = admin_client.get(reverse(PREPARATIONS))

    rows = response.context["cl"].result_list
    assert [r.name_en for r in rows] == ["twice", "once", "unused"]
    assert [(r.usage_count, r.component_count, r.food_count) for r in rows] == [
        (2, 2, 1),
        (1, 0, 0),
        (0, 0, 0),
    ]


def test_a_preparation_is_edited_with_its_components_and_foods(admin_client: Client):
    milk = ReferenceIngredient.objects.create(name_en="milk")
    mozzarella = Preparation.objects.create(name_en="mozzarella")

    page = admin_client.get(
        reverse("admin:products_preparation_change", args=[mozzarella.pk])
    )
    response = admin_client.post(
        reverse("admin:products_preparation_change", args=[mozzarella.pk]),
        {
            "name_en": "mozzarella",
            "name_fr": "mozzarella",
            "status": "to_review",
            "description": "",
            "components": [milk.pk],
        },
    )

    assert page.status_code == HTTPStatus.OK
    assert response.status_code == HTTPStatus.FOUND
    assert list(mozzarella.components.all()) == [milk]
    assert (
        admin_client.get(reverse("admin:products_preparation_add")).status_code
        == HTTPStatus.OK
    )


def test_a_preparation_is_found_by_its_name_from_an_ingredient_form(
    admin_client: Client,
):
    mozzarella = Preparation.objects.create(name_en="mozzarella")

    response = admin_client.get(
        reverse("admin:autocomplete"),
        {
            "term": "mozz",
            "app_label": "products",
            "model_name": "ingredient",
            "field_name": "preparation",
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert [r["id"] for r in response.json()["results"]] == [str(mozzarella.pk)]


def test_an_ingredient_that_is_a_preparation_is_listed_by_its_name(
    admin_client: Client,
):
    mozzarella = Preparation.objects.create(name_en="mozzarella")
    prepared_for(mozzarella, "3229820794556")

    response = admin_client.get(reverse("admin:products_ingredient_changelist"))

    assert "mozzarella" in response.content.decode()


def test_preparations_are_marked_as_curated_when_they_have_their_english_name(
    admin_client: Client,
):
    ready = Preparation.objects.create(name_en="mozzarella")
    waiting = Preparation.objects.create(name_fr="gnocchi")

    response = admin_client.post(
        reverse(PREPARATIONS),
        {"action": "mark_curated", "_selected_action": [ready.pk, waiting.pk]},
        follow=True,
    )

    ready.refresh_from_db()
    waiting.refresh_from_db()
    assert ready.status == Preparation.Status.CURATED
    assert waiting.status == Preparation.Status.TO_REVIEW
    assert any("lack an English name" in m for m in messages_of(response))
    assert any("1 preparation(s) marked as curated" in m for m in messages_of(response))


def test_the_forms_refuse_a_name_the_other_table_has(admin_client: Client):
    Preparation.objects.create(name_en="mozzarella")

    response = admin_client.post(
        reverse("admin:products_referenceingredient_add"),
        {"name_en": "Mozzarella", "name_fr": "", "status": "to_review"},
    )

    assert response.status_code == HTTPStatus.OK
    assert "A preparation already has this name." in response.content.decode()
    assert not ReferenceIngredient.objects.exists()


def test_the_pages_of_an_ingredient_open_whichever_it_is(admin_client: Client):
    """The forms for the reference and the preparation use the admins' ordering."""
    salt = ReferenceIngredient.objects.create(name_en="salt")
    mozzarella = Preparation.objects.create(name_en="mozzarella")
    used_by(salt, "3229820794556")
    prepared_for(mozzarella, "3229820794556")

    for ingredient in Ingredient.objects.all():
        url = reverse("admin:products_ingredient_change", args=[ingredient.pk])
        assert admin_client.get(url).status_code == HTTPStatus.OK
    assert (
        admin_client.get(reverse("admin:products_ingredient_add")).status_code
        == HTTPStatus.OK
    )
