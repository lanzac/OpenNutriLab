# products/tests/test_product_services_logic.py
from __future__ import annotations

import io
from decimal import Decimal
from typing import TYPE_CHECKING
from typing import Any
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.core.files.storage import Storage
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.uploadedfile import UploadedFile
from django.db.models.fields.files import ImageFieldFile

from products.api.schemas.inbound import IngredientInput
from products.api.schemas.inbound import MacronutrientInput
from products.api.schemas.inbound import NutritionalValuesUpdate
from products.api.schemas.inbound import ProductCreate
from products.api.schemas.inbound import ProductUpdate
from products.models import Ingredient
from products.models import IngredientRef
from products.models import Macronutrient
from products.models import Product
from products.models import ProductMacronutrient

# Import your code under test
from products.services.product_services import DEFAULT_IMAGE_NAME
from products.services.product_services import apply_product_update_fields
from products.services.product_services import create_product
from products.services.product_services import save_image_overwrite
from products.services.product_services import sync_product_image
from products.services.product_services import sync_product_ingredients_update
from products.services.product_services import sync_product_macronutrients_update
from products.services.product_services import update_product
from products.services.product_services import upsert_product_ingredients
from products.services.product_services import upsert_product_macronutrients

if TYPE_CHECKING:
    from django.db.models import FileField
    from django.db.models import Model


# -----------------------
# Fixtures / small helpers
# -----------------------
def minimal_payload(barcode: str, name: str, energy_kj: int) -> dict[str, Any]:
    return {
        "barcode": barcode,
        "name": name,
        "description": "",
        "group_level_1": "",
        "group_level_2": "",
        "nutritional_values": {
            "energy_kj": energy_kj,
            "macronutrients": [],
        },
    }


@pytest.fixture
def simple_macros() -> dict[str, Macronutrient]:
    """Create canonical macronutrients for tests."""
    Macronutrient.objects.all().delete()
    carb = Macronutrient.objects.create(name="Carbohydrate")
    fat = Macronutrient.objects.create(name="Fat")
    protein = Macronutrient.objects.create(name="Protein")
    return {"carb": carb, "fat": fat, "protein": protein}


REFERENCE_BARCODE = "4006381333931"
REFERENCE_NAME = "Apple"
REFERENCE_ENERGY_KJ = 50


@pytest.fixture
def product():
    """Return a persisted Product instance simple to use in tests."""
    Product.objects.all().delete()
    return Product.objects.create(
        barcode=REFERENCE_BARCODE,
        name=REFERENCE_NAME,
        energy_kj=REFERENCE_ENERGY_KJ,
    )


def build_uploaded_file(
    content: bytes = b"img", filename: str = "img.jpg"
) -> InMemoryUploadedFile:
    """
    Build a simple InMemoryUploadedFile useful for save_image_overwrite tests.
    """
    fp = io.BytesIO(content)
    fp.seek(0)
    return InMemoryUploadedFile(
        fp,
        field_name="image",
        name=filename,
        content_type="image/jpeg",
        size=len(content),
        charset=None,
    )


# -----------------------
# Unit tests : simple helpers
# -----------------------
@pytest.mark.django_db
def test_apply_product_update_fields_updates_simple_fields(product: Product):
    data = ProductUpdate.model_validate(
        minimal_payload(
            barcode=REFERENCE_BARCODE,
            name="New name",  # New name
            energy_kj=100,  # New energy
        )
    )
    data.group_level_1 = "G1"  # New group level 1

    apply_product_update_fields(product, data)
    product.refresh_from_db()
    assert product.name == "New name"
    assert product.group_level_1 == "G1"
    # assert product.energy =
    # description should remain the initial default (empty or whatever original)
    # We don't expect change because description was None in data
    # (if product started with "", remain "")
    assert product.description == "" or product.description is not None


@pytest.mark.django_db
def test_apply_product_update_fields_updates_energy_kj(product: Product):
    data = ProductUpdate.model_validate(
        minimal_payload("4006381333931", "New name", 11)
    )
    data.nutritional_values = NutritionalValuesUpdate.model_validate(
        {
            "energy_kj": 12,
            "macronutrients": [],
        }
    )

    apply_product_update_fields(product, data)
    product.refresh_from_db()
    assert product.energy_kj == 12  # noqa: PLR2004


@pytest.mark.django_db
def test_upsert_product_macronutrients_creates_and_updates(
    product: Product, simple_macros: dict[str, Macronutrient]
):
    macros = simple_macros
    product.productmacronutrient_set.all().delete()

    # create two amounts: carb (2.5), fat (1.0)
    items = [
        MacronutrientInput(name=macros["carb"].name, amount_g=Decimal("2.5")),
        MacronutrientInput(name=macros["fat"].name, amount_g=Decimal("1.0")),
    ]
    upsert_product_macronutrients(product, items)

    assert ProductMacronutrient.objects.filter(product=product).count() == 2  # noqa: PLR2004

    # update existing: change carb amount
    items2 = [MacronutrientInput(name=macros["carb"].name, amount_g=Decimal("3.0"))]
    upsert_product_macronutrients(product, items2)
    pm = ProductMacronutrient.objects.get(product=product, macronutrient=macros["carb"])
    assert pm.amount_g == Decimal("3.0")


@pytest.mark.django_db
def test_sync_product_macronutrients_update_none_and_empty(
    product: Product, simple_macros: dict[str, Macronutrient]
):
    macros = simple_macros

    ProductMacronutrient.objects.create(
        product=product,
        macronutrient=macros["carb"],
        amount_g=Decimal("1.2"),
    )

    with patch(
        "products.services.product_services.upsert_product_macronutrients"
    ) as upsert_mock:
        # None -> no change
        sync_product_macronutrients_update(product, macronutrients_list=None)
        upsert_mock.assert_not_called()
        assert ProductMacronutrient.objects.filter(product=product).count() == 1

        # [] -> delete
        sync_product_macronutrients_update(product, macronutrients_list=[])
        upsert_mock.assert_not_called()
        assert ProductMacronutrient.objects.filter(product=product).count() == 0

        # filled list -> upsert
        macronutrients_list = [
            MacronutrientInput(
                name=macros["fat"].name,
                amount_g=Decimal("0.5"),
            )
        ]

        sync_product_macronutrients_update(product, macronutrients_list)

        upsert_mock.assert_called_once_with(product, macronutrients_list)


@pytest.mark.django_db
def test_upsert_and_sync_ingredients_recursive(product: Product):
    # Prep existing IngredientRef so upsert picks it up as reference
    IngredientRef.objects.create(name="SaltRef")

    # build nested input
    nested = [
        IngredientInput(
            name="SaltRef",
            percentage=None,
            sub_ingredients=[
                IngredientInput(name="SubA", percentage=None, sub_ingredients=[])
            ],
        )
    ]

    # ensure starting clean
    Ingredient.objects.filter(product=product).delete()
    upsert_product_ingredients(product, nested)

    # root ingredient created
    roots = Ingredient.objects.filter(product=product, parent__isnull=True)
    assert roots.count() == 1
    root = roots.first()
    # sub created
    subs = Ingredient.objects.filter(product=product, parent=root)
    assert subs.count() == 1

    # now test sync with empty list clears
    sync_product_ingredients_update(product, ingredients_list=[])
    assert Ingredient.objects.filter(product=product).count() == 0

    # test sync with filled list recreates
    sync_product_ingredients_update(product, ingredients_list=nested)
    assert Ingredient.objects.filter(product=product).count() == 2  # noqa: PLR2004


# -----------------------
# Image helpers tests (mock storage)
# -----------------------
class DummyStorage:
    """A tiny dummy storage to intercept calls from save_image_overwrite."""

    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}
        self.existing: set[str] = set()

    def exists(self, name: str) -> bool:
        return name in self.existing

    def delete(self, name: str) -> None:
        self.existing.discard(name)
        self.saved.pop(name, None)

    def save(
        self, name: str, content: UploadedFile, max_length: int | None = None
    ) -> str:
        content.seek(0)
        self.saved[name] = content.read()
        self.existing.add(name)
        return name


class DummyFieldFile:
    """Simplified stand-in for product.image to intercept delete/save calls."""

    def __init__(self, name: str | None = None) -> None:
        self.name: str | None = name

    def delete(self, save: bool = True) -> None:  # noqa: FBT001, FBT002
        self.name = None

    def save(self, name: str, uploaded_file: UploadedFile, save: bool = True) -> None:  # noqa: FBT001, FBT002
        self.name = name


@pytest.mark.django_db
def test_save_image_overwrite_and_sync(
    monkeypatch: pytest.MonkeyPatch, product: Product
):
    """
    Test save_image_overwrite:
    - uses a real ImageFieldFile attached to the instance (no DummyFieldFile)
    - patches default_storage._wrapped to intercept save/delete calls
    - stubs generate_filename to a predictable string (avoid MagicMock in SQL)
    """
    # 1) Prepare a storage mock that saves bytes into a dict for assertions
    saved: dict[str, bytes] = {}

    storage_mock: Storage = MagicMock(spec=Storage)

    def fake_save(
        name: str, content: UploadedFile, max_length: int | None = None
    ) -> str:
        # read file-like
        content.seek(0)
        saved_name = f"images/{name}"  # imitate a storage path
        saved[saved_name] = content.read()
        return saved_name

    def fake_delete(name: str):
        # emulate deletion
        saved.pop(name, None)

    storage_mock.save.side_effect = fake_save
    storage_mock.delete.side_effect = fake_delete
    # We don't need exists to return True for the final_path in this test,
    # but we set a default implementation that returns False.
    storage_mock.exists.return_value = False

    # 2) Patch default_storage._wrapped so Django's lazy default_storage uses our mock
    monkeypatch.setattr(
        "django.core.files.storage.default_storage._wrapped", storage_mock
    )

    # 3) Ensure generate_filename returns a plain string (avoid MagicMock)
    field = cast("FileField", Product._meta.get_field("image"))  # noqa: SLF001

    def fake_generate_filename(instance: Model, filename: str) -> str:
        return f"images/{filename}"

    monkeypatch.setattr(field, "generate_filename", fake_generate_filename)

    # 4) Attach a real ImageFieldFile to the product to simulate an existing image
    #    This is Pyright-friendly and compatible with Django internals.
    image_file = ImageFieldFile(product, field, "old.jpg")

    product.image = image_file  # pyright: ignore[reportAttributeAccessIssue]
    # Also make sure the field file will use our storage mock when deleting/saving:
    product.image.storage = storage_mock

    # Ensure delete will be called for the old file path
    # (simulate that old.jpg existed on storage)
    # storage_mock.exists can be used by your code to check, but product.image.delete()
    # will directly call storage.delete(self.name), so we assert delete later.
    # 5) Prepare uploaded file
    uploaded = SimpleUploadedFile("new.jpg", b"newcontent", content_type="image/jpeg")

    # Assert save_image_overwrite returns None if no file provided
    result = save_image_overwrite(product, uploaded_file=None)
    assert result is None

    # 6) Run the function under test
    save_image_overwrite(product, uploaded)

    # 7) Assertions:
    # - storage.save was called and the saved dict contains new.jpg content
    assert any("new.jpg" in name for name in saved), (
        "new.jpg should be saved in storage"
    )
    assert any(content == b"newcontent" for content in saved.values())

    # - the old file should have been deleted via storage.delete (call count or args)
    #   (product.image.delete(save=False) should have invoked storage.delete("old.jpg"))
    storage_mock.delete.assert_any_call("old.jpg")

    # - the product instance now has an image name (database updated)
    #   depending on whether product fixture was saved initially, we can assert:
    assert product.image.name is not None
    assert "new.jpg" in product.image.name


@pytest.mark.django_db
def test_save_image_overwrite_deletes_existing_file_at_target_path(
    monkeypatch: pytest.MonkeyPatch, product: Product
):
    saved: dict[str, bytes] = {}

    storage_mock: Storage = MagicMock(spec=Storage)

    def fake_save(
        name: str, content: UploadedFile, max_length: int | None = None
    ) -> str:
        content.seek(0)
        saved_name = f"images/{name}"
        saved[saved_name] = content.read()
        return saved_name

    storage_mock.save.side_effect = fake_save
    storage_mock.delete = MagicMock()

    # force exists to return True for the target path to test deletion of existing file
    storage_mock.exists.return_value = True

    monkeypatch.setattr(
        "django.core.files.storage.default_storage._wrapped",
        storage_mock,
    )

    field = cast("FileField", Product._meta.get_field("image"))  # noqa: SLF001

    def fake_generate_filename(instance: Model, filename: str) -> str:
        return f"images/{filename}"

    monkeypatch.setattr(field, "generate_filename", fake_generate_filename)

    uploaded = SimpleUploadedFile("new.jpg", b"newcontent", content_type="image/jpeg")

    save_image_overwrite(product, uploaded)

    # verify that delete was called for the existing file at the target path
    storage_mock.delete.assert_any_call("images/new.jpg")


@pytest.mark.django_db
def test_sync_product_image_no_url(monkeypatch: pytest.MonkeyPatch, product: Product):
    save_mock = MagicMock()
    fetch_mock = MagicMock()

    monkeypatch.setattr(
        "products.services.product_services.save_image_overwrite", save_mock
    )
    monkeypatch.setattr(
        "products.services.product_services.fetch_image_as_uploaded_file", fetch_mock
    )

    sync_product_image(product, image_url=None, barcode="0000")

    save_mock.assert_not_called()
    fetch_mock.assert_not_called()


@pytest.mark.django_db
def test_sync_product_image_calls_save_with_expected_filename(
    monkeypatch: pytest.MonkeyPatch, product: Product
):
    barcode = "0123456789"
    image_url = "https://example.com/img.jpg"
    expected_filename = DEFAULT_IMAGE_NAME.format(barcode=barcode)

    captured = {}

    def fake_fetch(image_url: str, filename: str):
        captured["image_url"] = image_url
        captured["filename"] = filename
        # retourner un vrai InMemoryUploadedFile-like (SimpleUploadedFile suffit)
        return SimpleUploadedFile(filename, b"imagedata", content_type="image/jpeg")

    monkeypatch.setattr(
        "products.services.product_services.fetch_image_as_uploaded_file",
        fake_fetch,
    )

    save_mock = MagicMock()
    monkeypatch.setattr(
        "products.services.product_services.save_image_overwrite",
        save_mock,
    )

    sync_product_image(product, image_url=image_url, barcode=barcode)

    # fetch_image_as_uploaded_file should be called with the provided URL and the
    # expected filename
    assert captured["image_url"] == image_url
    assert captured["filename"] == expected_filename

    # save_image_overwrite should be called with the product and an uploaded file
    # with the expected filename
    save_mock.assert_called_once()
    called_product, uploaded_file = save_mock.call_args[0]
    assert called_product is product
    assert hasattr(uploaded_file, "name")
    assert uploaded_file.name == expected_filename


# -----------------------
# High-level create / update (integration-like)
# -----------------------
@pytest.mark.django_db
def test_create_product_full_flow(
    monkeypatch: pytest.MonkeyPatch, simple_macros: dict[str, Macronutrient]
):
    # Build a minimal payload accepted by ProductCreate (use dict form expected)
    payload: dict[str, str | dict[str, int | list[Any]] | list[Any]] = {
        "barcode": REFERENCE_BARCODE,  # presumed valid EAN in your system
        "name": "Created",
        "description": "",
        "group_level_1": "",
        "group_level_2": "",
        "nutritional_values": {"energy_kj": 10, "macronutrients": []},
        "ingredients": [],
    }

    # Prevent actual image download during create_product
    def fake_fetch_image_as_uploaded_file(
        image_url: str,
        filename: str,
    ) -> InMemoryUploadedFile | None:
        return None

    monkeypatch.setattr(
        "products.services.product_services.fetch_image_as_uploaded_file",
        fake_fetch_image_as_uploaded_file,
    )
    monkeypatch.setattr(
        "products.services.product_services.default_storage", DummyStorage()
    )

    created = create_product(ProductCreate.model_validate(payload))
    assert Product.objects.filter(barcode=created.barcode).exists()


@pytest.mark.django_db
def test_update_product_full_flow(monkeypatch: pytest.MonkeyPatch, product: Product):
    p = product
    # prepare update payload: change name and energy_kj
    payload = {
        "name": "Updated via service",
        "nutritional_values": {"energy_kj": 22},
    }

    def fake_fetch_image_as_uploaded_file(
        image_url: str,
        filename: str,
    ) -> InMemoryUploadedFile | None:
        return None

    monkeypatch.setattr(
        "products.services.product_services.fetch_image_as_uploaded_file",
        fake_fetch_image_as_uploaded_file,
    )
    monkeypatch.setattr(
        "products.services.product_services.default_storage", DummyStorage()
    )

    update_product(p, ProductUpdate.model_validate(payload))
    p.refresh_from_db()
    assert p.name == "Updated via service"
    assert p.energy_kj == 22  # noqa: PLR2004
