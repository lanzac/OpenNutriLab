import re
from decimal import Decimal
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission
from django.http.response import HttpResponse
from django.test import Client
from django.urls import reverse
from pytest_django.fixtures import SettingsWrapper

from opennutrilab.products.models import Additive
from opennutrilab.products.models import AdditiveNutrient
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
ADDITIVES = "admin:products_additive_changelist"
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
# Making a preparation of references
# ----------------------------------------------------------------------------
def seen_with(
    reference: ReferenceIngredient, *parts: ReferenceIngredient, barcode: str
) -> None:
    """The reference on a label, with the parts that label lists for it."""
    product, _created = Product.objects.get_or_create(
        barcode=barcode, defaults={"name": barcode}
    )
    ingredient = Ingredient.objects.create(product=product, reference=reference)
    for part in parts:
        Ingredient.objects.create(product=product, parent=ingredient, reference=part)


def made_preparations(
    client: Client, references: list[ReferenceIngredient], **extra: Any
) -> Any:
    return client.post(
        reverse(REFERENCES),
        {
            "action": "make_preparation",
            "_selected_action": [r.pk for r in references],
            **extra,
        },
        follow=True,
    )


@pytest.fixture
def cheese() -> dict[str, ReferenceIngredient]:
    """A mozzarella seen made of milk and salt, and the two it was made of."""
    things = {
        name: ReferenceIngredient.objects.create(name_en=name, name_fr=name_fr)
        for name, name_fr in (
            ("mozzarella", "mozzarelle"),
            ("milk", "lait"),
            ("salt", "sel"),
        )
    }
    seen_with(things["mozzarella"], things["milk"], things["salt"], barcode="1")
    return things


def test_the_references_say_how_many_times_they_were_seen_with_parts(
    admin_client: Client, cheese: dict[str, ReferenceIngredient]
):
    seen_with(cheese["mozzarella"], barcode="2")  # Listed with no parts.
    seen_with(cheese["mozzarella"], cheese["milk"], barcode="3")

    response = admin_client.get(reverse(REFERENCES))

    rows = {r.name_en: r for r in response.context["cl"].result_list}
    assert rows["mozzarella"].usage_count == 3  # noqa: PLR2004
    assert rows["mozzarella"].with_parts_count == 2  # noqa: PLR2004
    assert rows["milk"].with_parts_count == 0


def test_the_action_shows_what_each_reference_becomes_and_changes_nothing(
    admin_client: Client, cheese: dict[str, ReferenceIngredient]
):
    response = admin_client.post(
        reverse(REFERENCES),
        {
            "action": "make_preparation",
            "_selected_action": [cheese["mozzarella"].pk],
        },
    )

    assert response.status_code == HTTPStatus.OK
    page = response.content.decode()
    assert "mozzarella" in page
    # The components it gets: the parts seen on the label.
    assert "milk" in page
    assert "salt" in page
    assert not Preparation.objects.exists()
    assert ReferenceIngredient.objects.filter(name_en="mozzarella").exists()


def test_applying_makes_the_preparation_and_repoints_the_ingredients(
    admin_client: Client, cheese: dict[str, ReferenceIngredient]
):
    mozzarella = cheese["mozzarella"]

    response = made_preparations(admin_client, [mozzarella], apply="on")

    preparation = Preparation.objects.get()
    assert (preparation.name_en, preparation.name_fr) == ("mozzarella", "mozzarelle")
    assert set(preparation.components.all()) == {cheese["milk"], cheese["salt"]}
    assert not ReferenceIngredient.objects.filter(name_en="mozzarella").exists()
    assert [i.preparation for i in Ingredient.objects.filter(parent=None)] == [
        preparation
    ]
    assert any("mozzarella" in m for m in messages_of(response))
    assert response.redirect_chain


def test_only_the_selected_references_are_converted(
    admin_client: Client, cheese: dict[str, ReferenceIngredient]
):
    made_preparations(admin_client, [cheese["mozzarella"]], apply="on")

    assert set(ReferenceIngredient.objects.values_list("name_en", flat=True)) == {
        "milk",
        "salt",
    }


def test_a_reference_that_cannot_be_converted_is_told_and_the_others_are(
    admin_client: Client, cheese: dict[str, ReferenceIngredient]
):
    gnocchi = ReferenceIngredient.objects.create(name_en="gnocchi")
    Preparation.objects.create(name_en="Gnocchi")
    seen_with(cheese["salt"], cheese["milk"], barcode="4")

    shown = made_preparations(admin_client, [gnocchi, cheese["salt"]])
    response = made_preparations(admin_client, [gnocchi, cheese["salt"]], apply="on")

    assert "already has the name of gnocchi" in shown.content.decode()
    # Only the salt is converted, the other stays as it was.
    assert set(Preparation.objects.values_list("name_en", flat=True)) == {
        "Gnocchi",
        "salt",
    }
    assert ReferenceIngredient.objects.filter(name_en="gnocchi").exists()
    texts = messages_of(response)
    assert any("already has the name of gnocchi" in m for m in texts)
    assert any("made into preparations: salt" in m for m in texts)


def test_a_reference_that_is_a_component_of_a_preparation_is_converted_in_it(
    admin_client: Client, cheese: dict[str, ReferenceIngredient]
):
    pizza = Preparation.objects.create(name_en="pizza")
    pizza.components.add(cheese["mozzarella"], cheese["salt"])

    made_preparations(admin_client, [cheese["mozzarella"]], apply="on")

    mozzarella = Preparation.objects.get(name_en="mozzarella")
    assert list(pizza.components.all()) == [cheese["salt"]]
    assert list(pizza.preparation_components.all()) == [mozzarella]


def test_when_none_can_be_converted_the_curator_is_told_and_gets_no_page(
    admin_client: Client, cheese: dict[str, ReferenceIngredient]
):
    Preparation.objects.create(name_en="mozzarella")

    response = made_preparations(admin_client, [cheese["mozzarella"]])

    assert any("already has the name" in m for m in messages_of(response))
    assert "Make preparations" not in response.content.decode()
    assert ReferenceIngredient.objects.filter(name_en="mozzarella").exists()


def test_making_a_preparation_needs_the_permissions_it_uses(
    client: Client, cheese: dict[str, ReferenceIngredient]
):
    editor = UserFactory(is_staff=True)
    editor.user_permissions.add(
        *Permission.objects.filter(
            codename__in=(
                "view_referenceingredient",
                "change_referenceingredient",
                "change_ingredient",
                "delete_referenceingredient",
                # Not "add_preparation".
            )
        )
    )
    client.force_login(editor)

    made_preparations(client, [cheese["mozzarella"]], apply="on")

    assert not Preparation.objects.exists()
    assert ReferenceIngredient.objects.filter(name_en="mozzarella").exists()


# ----------------------------------------------------------------------------
# Making an additive of references
# ----------------------------------------------------------------------------
def made_additives(
    client: Client, references: list[ReferenceIngredient], **extra: Any
) -> Any:
    return client.post(
        reverse(REFERENCES),
        {
            "action": "make_additive",
            "_selected_action": [r.pk for r in references],
            **extra,
        },
        follow=True,
    )


@pytest.fixture
def known() -> dict[str, Any]:
    """A reference named like an additive, one like its plural, a new one."""
    citric = Additive.objects.create(
        name_en="Citric acid", name_fr="Acide citrique", code="E330"
    )
    Additive.objects.create(name_fr="Lécithines", code="E322")
    return {
        "citric": citric,
        "same": ReferenceIngredient.objects.create(name_fr="acide citrique"),
        "plural": ReferenceIngredient.objects.create(name_fr="lécithine"),
        "new": ReferenceIngredient.objects.create(name_fr="gomme xanthane"),
    }


def test_the_references_known_as_additives_are_filtered_out_of_the_list(
    admin_client: Client, known: dict[str, Any]
):
    response = admin_client.get(reverse(REFERENCES), {"known_additive": "known"})

    assert {r.name_fr for r in response.context["cl"].result_list} == {
        "acide citrique",
        "lécithine",
    }


def test_making_an_additive_shows_what_each_reference_becomes_first(
    admin_client: Client, known: dict[str, Any]
):
    response = admin_client.post(
        reverse(REFERENCES),
        {
            "action": "make_additive",
            "_selected_action": [known["same"].pk, known["plural"].pk, known["new"].pk],
        },
    )

    page = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "Merged into the additive Citric acid E330" in page
    assert "Looks like the additive Lécithines E322" in page
    assert "A new additive, to review." in page
    assert ReferenceIngredient.objects.count() == 3  # noqa: PLR2004
    assert Additive.objects.count() == 2  # noqa: PLR2004


def ticked_boxes(page: str) -> dict[str, bool]:
    """Which of the boxes "convert_<id>" are ticked."""
    return {
        match.group(1): "checked" in match.group(0)
        for match in re.finditer(
            r'<input type="checkbox"[^>]*name="convert_(\d+)"[^>]*>', page
        )
    }


def test_a_sure_match_and_a_new_additive_are_ticked_and_a_likely_one_is_not(
    admin_client: Client, known: dict[str, Any]
):
    response = admin_client.post(
        reverse(REFERENCES),
        {
            "action": "make_additive",
            "_selected_action": [known["same"].pk, known["plural"].pk, known["new"].pk],
        },
    )

    boxes = ticked_boxes(response.content.decode())

    assert boxes == {
        str(known["same"].pk): True,
        str(known["plural"].pk): False,
        str(known["new"].pk): True,
    }


def test_applying_converts_the_ticked_references_only(
    admin_client: Client, known: dict[str, Any]
):
    used_by(known["same"], "3229820794556")
    used_by(known["new"], "3229820794556")
    used_by(known["plural"], "3229820794556")

    response = made_additives(
        admin_client,
        [known["same"], known["plural"], known["new"]],
        apply="on",
        **{f"convert_{known['same'].pk}": "on", f"convert_{known['new'].pk}": "on"},
    )

    assert set(ReferenceIngredient.objects.values_list("name_fr", flat=True)) == {
        "lécithine"
    }
    # Merged into the additive that was there, and a new one made: three in all.
    assert Additive.objects.count() == 3  # noqa: PLR2004
    assert known["citric"].usages.count() == 1
    assert Additive.objects.get(name_fr="gomme xanthane").usages.count() == 1
    assert any("2 reference(s) made into additives" in m for m in messages_of(response))


def test_a_reference_that_cannot_be_made_an_additive_is_told_and_the_others_are(
    admin_client: Client, known: dict[str, Any]
):
    sauce = Preparation.objects.create(name_en="sauce")
    sauce.components.add(known["new"])
    refused = [known["new"]]

    shown = made_additives(admin_client, [*refused, known["same"]])
    response = made_additives(
        admin_client,
        [*refused, known["same"]],
        apply="on",
        **{f"convert_{known['new'].pk}": "on", f"convert_{known['same'].pk}": "on"},
    )

    page = shown.content.decode()
    assert "component of sauce" in page
    # A reference that cannot be converted has no box to tick.
    assert str(known["new"].pk) not in ticked_boxes(page)
    assert ReferenceIngredient.objects.filter(pk=known["new"].pk).exists()
    assert not ReferenceIngredient.objects.filter(pk=known["same"].pk).exists()
    texts = messages_of(response)
    assert any("component of sauce" in m for m in texts)
    assert any("1 reference(s) made into additives" in m for m in texts)


def test_when_no_reference_can_be_made_an_additive_the_curator_gets_no_page(
    admin_client: Client, known: dict[str, Any]
):
    sauce = Preparation.objects.create(name_en="sauce")
    sauce.components.add(known["new"])

    response = made_additives(admin_client, [known["new"]])

    assert any("component of sauce" in m for m in messages_of(response))
    assert "Make additives" not in response.content.decode().split("action-select")[-1]
    assert ReferenceIngredient.objects.filter(pk=known["new"].pk).exists()


def test_making_an_additive_needs_the_permissions_it_uses(
    client: Client, known: dict[str, Any]
):
    editor = UserFactory(is_staff=True)
    editor.user_permissions.add(
        *Permission.objects.filter(
            codename__in=(
                "view_referenceingredient",
                "change_referenceingredient",
                "change_ingredient",
                "delete_referenceingredient",
                # Not "add_additive".
            )
        )
    )
    client.force_login(editor)

    made_additives(
        client, [known["new"]], apply="on", **{f"convert_{known['new'].pk}": "on"}
    )

    assert ReferenceIngredient.objects.filter(pk=known["new"].pk).exists()
    assert Additive.objects.count() == 2  # noqa: PLR2004


# ----------------------------------------------------------------------------
# Proposing English names
# ----------------------------------------------------------------------------
TRANSLATE = "opennutrilab.products.services.english_names.translate"


def names_proposed(
    client: Client, references: list[ReferenceIngredient], **extra: Any
) -> Any:
    return client.post(
        reverse(REFERENCES),
        {
            "action": "propose_english_names",
            "_selected_action": [r.pk for r in references],
            **extra,
        },
        follow=True,
    )


@pytest.fixture
def unnamed() -> dict[str, ReferenceIngredient]:
    """Two references with no English name, and one that has it."""
    return {
        "onion": ReferenceIngredient.objects.create(name_fr="oignon grillé"),
        "juice": ReferenceIngredient.objects.create(name_fr="jus d'oignon concentré"),
        "named": ReferenceIngredient.objects.create(name_en="milk", name_fr="lait"),
    }


def test_the_references_are_filtered_by_having_an_english_name(
    admin_client: Client, unnamed: dict[str, ReferenceIngredient]
):
    response = admin_client.get(reverse(REFERENCES), {"english_name": "without"})
    assert {r.name_fr for r in response.context["cl"].result_list} == {
        "oignon grillé",
        "jus d'oignon concentré",
    }

    response = admin_client.get(reverse(REFERENCES), {"english_name": "with"})
    assert [r.name_fr for r in response.context["cl"].result_list] == ["lait"]


def test_the_proposals_are_shown_with_their_source_and_nothing_is_written(
    admin_client: Client,
    unnamed: dict[str, ReferenceIngredient],
    settings: SettingsWrapper,
):
    settings.TRANSLATION_URL = "http://translator:5000"
    with patch(TRANSLATE, return_value="grilled onion"):
        response = names_proposed(admin_client, list(unnamed.values()))

    page = response.content.decode()
    assert 'value="grilled onion"' in page
    assert "Machine translation" in page
    # The reference that has an English name is not proposed one.
    assert "lait" not in page
    assert (
        not ReferenceIngredient.objects.filter(name_fr="oignon grillé")
        .exclude(name_en="")
        .exists()
    )


def test_a_machine_translation_is_not_ticked_for_the_curator(
    admin_client: Client,
    unnamed: dict[str, ReferenceIngredient],
    settings: SettingsWrapper,
):
    settings.TRANSLATION_URL = "http://translator:5000"
    with patch(TRANSLATE, return_value="grilled onion"):
        response = names_proposed(admin_client, [unnamed["onion"]])

    box = re.search(
        r'<input type="checkbox"[^>]*apply_\d+[^>]*>', response.content.decode()
    )
    assert box is not None
    assert "checked" not in box.group(0)


def test_a_name_from_the_taxonomy_is_ticked_already(
    admin_client: Client, unnamed: dict[str, ReferenceIngredient]
):
    IngredientTaxon.objects.create(
        off_id="en:grilled-onion", name_en="grilled onion", name_fr="oignon grillé"
    )

    response = names_proposed(admin_client, [unnamed["onion"]])

    box = re.search(
        r'<input type="checkbox"[^>]*apply_\d+[^>]*>', response.content.decode()
    )
    assert box is not None
    assert "checked" in box.group(0)


def test_the_page_says_when_no_translator_is_set_and_does_not_blame_one(
    admin_client: Client, unnamed: dict[str, ReferenceIngredient]
):
    response = names_proposed(admin_client, [unnamed["onion"]])

    assert "No translator is set" in response.content.decode()
    assert not any("did not answer" in m for m in messages_of(response))


def test_a_translator_that_does_not_answer_is_reported(
    admin_client: Client,
    unnamed: dict[str, ReferenceIngredient],
    settings: SettingsWrapper,
):
    settings.TRANSLATION_URL = "http://translator:5000"
    with patch(TRANSLATE, return_value=None):
        response = names_proposed(admin_client, [unnamed["onion"]])

    assert any("did not answer" in m for m in messages_of(response))


def test_only_the_ticked_references_are_named_with_what_is_in_their_field(
    admin_client: Client, unnamed: dict[str, ReferenceIngredient]
):
    onion, juice = unnamed["onion"], unnamed["juice"]

    response = names_proposed(
        admin_client,
        [onion, juice],
        apply="on",
        **{
            f"apply_{onion.pk}": "on",
            # Edited by the curator.
            f"name_{onion.pk}": "  roasted   onion ",
            # Not ticked: left alone.
            f"name_{juice.pk}": "onion juice",
        },
    )

    onion.refresh_from_db()
    juice.refresh_from_db()
    assert (onion.name_en, juice.name_en) == ("roasted onion", "")
    # The status is the curator's to change: a name is not a curation.
    assert onion.status == ReferenceIngredient.Status.TO_REVIEW
    assert any("1 item(s) given an English name" in m for m in messages_of(response))


def test_a_ticked_reference_with_an_empty_field_is_left_alone(
    admin_client: Client, unnamed: dict[str, ReferenceIngredient]
):
    onion = unnamed["onion"]

    names_proposed(
        admin_client,
        [onion],
        apply="on",
        **{f"apply_{onion.pk}": "on", f"name_{onion.pk}": "  "},
    )

    onion.refresh_from_db()
    assert onion.name_en == ""


def test_a_name_that_is_already_taken_is_refused_and_the_others_are_given(
    admin_client: Client, unnamed: dict[str, ReferenceIngredient]
):
    onion, juice = unnamed["onion"], unnamed["juice"]
    Preparation.objects.create(name_en="Roasted onion")

    response = names_proposed(
        admin_client,
        [onion, juice],
        apply="on",
        **{
            f"apply_{onion.pk}": "on",
            f"name_{onion.pk}": "roasted onion",
            f"apply_{juice.pk}": "on",
            f"name_{juice.pk}": "onion juice",
        },
    )

    onion.refresh_from_db()
    juice.refresh_from_db()
    assert (onion.name_en, juice.name_en) == ("", "onion juice")
    assert any(
        "already the English name of Roasted onion" in m for m in messages_of(response)
    )


def test_the_same_name_given_to_two_references_is_given_to_one_only(
    admin_client: Client, unnamed: dict[str, ReferenceIngredient]
):
    onion, juice = unnamed["onion"], unnamed["juice"]

    response = names_proposed(
        admin_client,
        [onion, juice],
        apply="on",
        **{
            f"apply_{onion.pk}": "on",
            f"name_{onion.pk}": "onion",
            f"apply_{juice.pk}": "on",
            f"name_{juice.pk}": "ONION",
        },
    )

    onion.refresh_from_db()
    juice.refresh_from_db()
    # The page goes through them by their French name: "jus" before "oignon".
    assert (juice.name_en, onion.name_en) == ("ONION", "")
    assert any("already the English name" in m for m in messages_of(response))


def test_references_that_all_have_an_english_name_get_a_message_and_no_page(
    admin_client: Client, unnamed: dict[str, ReferenceIngredient]
):
    response = names_proposed(admin_client, [unnamed["named"]])

    assert any("already have an English name" in m for m in messages_of(response))
    assert "Give the ticked names" not in response.content.decode()


def test_proposing_names_needs_the_permission_to_change_references(
    client: Client, unnamed: dict[str, ReferenceIngredient]
):
    viewer = UserFactory(is_staff=True)
    viewer.user_permissions.add(
        Permission.objects.get(codename="view_referenceingredient")
    )
    client.force_login(viewer)
    onion = unnamed["onion"]

    names_proposed(
        client,
        [onion],
        apply="on",
        **{f"apply_{onion.pk}": "on", f"name_{onion.pk}": "roasted onion"},
    )

    onion.refresh_from_db()
    assert onion.name_en == ""


# ----------------------------------------------------------------------------
# Proposing English names for additives and preparations
# ----------------------------------------------------------------------------
def names_proposed_for(client: Client, url: str, items: list[Any], **extra: Any) -> Any:
    return client.post(
        reverse(url),
        {
            "action": "propose_english_names",
            "_selected_action": [i.pk for i in items],
            **extra,
        },
        follow=True,
    )


def test_the_additives_are_given_an_english_name_the_same_way(
    admin_client: Client, settings: SettingsWrapper
):
    settings.TRANSLATION_URL = "http://translator:5000"
    xanthan = Additive.objects.create(name_fr="gomme xanthane", code="E415")
    named = Additive.objects.create(name_en="citric acid", code="E330")

    with patch(TRANSLATE, return_value="xanthan gum"):
        page = names_proposed_for(admin_client, ADDITIVES, [xanthan, named])

    html = page.content.decode()
    assert 'value="xanthan gum"' in html
    assert "Machine translation" in html
    # What has its English name is not proposed one, and the page says what it is.
    assert "citric acid" not in html
    assert ">Additive<" in html

    names_proposed_for(
        admin_client,
        ADDITIVES,
        [xanthan],
        apply="on",
        **{f"apply_{xanthan.pk}": "on", f"name_{xanthan.pk}": "xanthan gum"},
    )

    xanthan.refresh_from_db()
    assert xanthan.name_en == "xanthan gum"
    # Its code and class are what they were.
    assert xanthan.code == "E415"


def test_an_additive_cannot_be_given_the_english_name_of_a_reference(
    admin_client: Client,
):
    ReferenceIngredient.objects.create(name_en="Xanthan gum")
    xanthan = Additive.objects.create(name_fr="gomme xanthane", code="E415")

    response = names_proposed_for(
        admin_client,
        ADDITIVES,
        [xanthan],
        apply="on",
        **{f"apply_{xanthan.pk}": "on", f"name_{xanthan.pk}": "xanthan gum"},
    )

    xanthan.refresh_from_db()
    assert xanthan.name_en == ""
    assert any(
        "already the English name of Xanthan gum" in m for m in messages_of(response)
    )


def test_the_additives_are_filtered_by_having_an_english_name(admin_client: Client):
    Additive.objects.create(name_fr="gomme xanthane", code="E415")
    Additive.objects.create(name_en="citric acid", code="E330")

    response = admin_client.get(reverse(ADDITIVES), {"english_name": "without"})

    assert [a.code for a in response.context["cl"].result_list] == ["E415"]


def test_the_preparations_are_given_an_english_name_the_same_way(
    admin_client: Client,
):
    gnocchi = Preparation.objects.create(name_fr="gnocchi à la pomme de terre")
    IngredientTaxon.objects.create(
        off_id="en:potato-gnocchi",
        name_en="potato gnocchi",
        name_fr="gnocchi à la pomme de terre",
    )

    page = names_proposed_for(admin_client, PREPARATIONS, [gnocchi])

    assert 'value="potato gnocchi"' in page.content.decode()
    assert "OpenFoodFacts taxonomy" in page.content.decode()

    names_proposed_for(
        admin_client,
        PREPARATIONS,
        [gnocchi],
        apply="on",
        **{f"apply_{gnocchi.pk}": "on", f"name_{gnocchi.pk}": "potato gnocchi"},
    )

    gnocchi.refresh_from_db()
    assert gnocchi.name_en == "potato gnocchi"
    assert gnocchi.status == Preparation.Status.TO_REVIEW


def test_proposing_names_for_additives_needs_the_permission_to_change_them(
    client: Client,
):
    viewer = UserFactory(is_staff=True)
    viewer.user_permissions.add(Permission.objects.get(codename="view_additive"))
    client.force_login(viewer)
    xanthan = Additive.objects.create(name_fr="gomme xanthane", code="E415")

    names_proposed_for(
        client,
        ADDITIVES,
        [xanthan],
        apply="on",
        **{f"apply_{xanthan.pk}": "on", f"name_{xanthan.pk}": "xanthan gum"},
    )

    xanthan.refresh_from_db()
    assert xanthan.name_en == ""


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
    twice.components.set([ReferenceIngredient.objects.create(name_en="milk")])
    twice.preparation_components.set([once])
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
    brine = Preparation.objects.create(name_en="brine")
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
            "preparation_components": [brine.pk],
        },
    )

    assert page.status_code == HTTPStatus.OK
    assert response.status_code == HTTPStatus.FOUND
    assert list(mozzarella.components.all()) == [milk]
    assert list(mozzarella.preparation_components.all()) == [brine]
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
    citric = Additive.objects.create(name_en="citric acid", code="E330")
    used_by(salt, "3229820794556")
    prepared_for(mozzarella, "3229820794556")
    added_to(citric, "3229820794556")

    for ingredient in Ingredient.objects.all():
        url = reverse("admin:products_ingredient_change", args=[ingredient.pk])
        assert admin_client.get(url).status_code == HTTPStatus.OK
    assert (
        admin_client.get(reverse("admin:products_ingredient_add")).status_code
        == HTTPStatus.OK
    )


# ----------------------------------------------------------------------------
# Additives
# ----------------------------------------------------------------------------
def added_to(additive: Additive, *barcodes: str) -> None:
    for barcode in barcodes:
        product, _created = Product.objects.get_or_create(
            barcode=barcode, defaults={"name": barcode}
        )
        Ingredient.objects.create(product=product, additive=additive)


def test_the_additives_are_listed_most_used_first_with_their_counts(
    admin_client: Client,
):
    Additive.objects.create(name_en="unused")
    once = Additive.objects.create(name_en="once", code="E100")
    twice = Additive.objects.create(name_en="twice", code="E200")
    added_to(twice, "3229820794556", "3017620422003")
    added_to(once, "3229820794556")
    AdditiveNutrient.objects.create(
        additive=twice,
        nutrient=Nutrient.objects.get(code="fat"),
        amount=Decimal(1),
    )
    twice.source_foods.add(
        SourceFood.objects.create(
            source=Source.objects.create(code="ciqual-2025", name="Ciqual"), code="1"
        )
    )

    response = admin_client.get(reverse(ADDITIVES))

    rows = response.context["cl"].result_list
    assert [r.name_en for r in rows] == ["twice", "once", "unused"]
    assert [(r.usage_count, r.nutrient_count, r.food_count) for r in rows] == [
        (2, 1, 1),
        (1, 0, 0),
        (0, 0, 0),
    ]


def test_an_additive_is_edited_with_its_code_function_and_nutrients(
    admin_client: Client,
):
    fat = Nutrient.objects.get(code="fat")
    citric = Additive.objects.create(name_en="citric acid")
    url = reverse("admin:products_additive_change", args=[citric.pk])

    page = admin_client.get(url)
    response = admin_client.post(
        url,
        {
            "name_en": "citric acid",
            "name_fr": "acide citrique",
            "code": " e 330",
            "function": "acid",
            "status": "to_review",
            "description": "",
            "nutrients-TOTAL_FORMS": "1",
            "nutrients-INITIAL_FORMS": "0",
            "nutrients-MIN_NUM_FORMS": "0",
            "nutrients-MAX_NUM_FORMS": "1000",
            "nutrients-0-nutrient": fat.pk,
            "nutrients-0-amount": "0",
            "nutrients-0-note": "No fat in it.",
        },
    )

    assert page.status_code == HTTPStatus.OK
    assert response.status_code == HTTPStatus.FOUND
    citric.refresh_from_db()
    assert (citric.code, citric.function) == ("E330", "acid")
    [brought] = citric.nutrients.all()
    assert (brought.nutrient, brought.amount, brought.note) == (
        fat,
        Decimal(0),
        "No fat in it.",
    )
    assert (
        admin_client.get(reverse("admin:products_additive_add")).status_code
        == HTTPStatus.OK
    )


def test_an_additive_is_found_by_its_code_or_name_from_an_ingredient_form(
    admin_client: Client,
):
    citric = Additive.objects.create(name_en="citric acid", code="E330")

    for term in ("E33", "citric"):
        response = admin_client.get(
            reverse("admin:autocomplete"),
            {
                "term": term,
                "app_label": "products",
                "model_name": "ingredient",
                "field_name": "additive",
            },
        )

        assert response.status_code == HTTPStatus.OK
        assert [r["id"] for r in response.json()["results"]] == [str(citric.pk)]


def test_an_ingredient_that_is_an_additive_is_listed_by_its_name(
    admin_client: Client,
):
    citric = Additive.objects.create(name_en="citric acid", code="E330")
    added_to(citric, "3229820794556")

    response = admin_client.get(reverse("admin:products_ingredient_changelist"))

    assert "citric acid (E330)" in response.content.decode()


def test_additives_are_marked_as_curated_when_they_have_their_english_name(
    admin_client: Client,
):
    ready = Additive.objects.create(name_en="citric acid", code="E330")
    waiting = Additive.objects.create(name_fr="acide citrique", code="E331")

    response = admin_client.post(
        reverse(ADDITIVES),
        {"action": "mark_curated", "_selected_action": [ready.pk, waiting.pk]},
        follow=True,
    )

    ready.refresh_from_db()
    waiting.refresh_from_db()
    assert (ready.status, waiting.status) == ("curated", "to_review")
    texts = messages_of(response)
    assert any("1 additive(s) lack an English name" in m for m in texts)
    assert any("1 additive(s) marked as curated" in m for m in texts)


def test_the_additives_are_filtered_by_function_and_by_source_foods(
    admin_client: Client,
):
    acid = Additive.objects.create(name_en="citric acid", function="acid")
    Additive.objects.create(name_en="carmine", function="colour")

    response = admin_client.get(reverse(ADDITIVES), {"function": "acid"})
    assert [r.name_en for r in response.context["cl"].result_list] == [acid.name_en]

    response = admin_client.get(reverse(ADDITIVES), {"source_foods": "with"})
    assert list(response.context["cl"].result_list) == []


def test_the_forms_refuse_a_name_an_additive_has(admin_client: Client):
    Additive.objects.create(name_en="citric acid", code="E330")

    as_reference = admin_client.post(
        reverse("admin:products_referenceingredient_add"),
        {"name_en": "Citric acid", "name_fr": "", "status": "to_review"},
    )
    as_preparation = admin_client.post(
        reverse("admin:products_preparation_add"),
        {"name_en": "citric acid", "name_fr": "", "status": "to_review"},
    )

    assert "An additive already has this name." in as_reference.content.decode()
    assert "An additive already has this name." in as_preparation.content.decode()
    assert not ReferenceIngredient.objects.exists()
    assert not Preparation.objects.exists()
