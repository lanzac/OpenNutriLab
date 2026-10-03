from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from typing import Any
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests
from django.core.files.storage import Storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.uploadedfile import UploadedFile
from django.db.models.fields.files import ImageFieldFile

from opennutrilab.products.api.schemas.inbound import ProductCreate
from opennutrilab.products.api.schemas.inbound import ProductUpdate
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import IngredientRef
from opennutrilab.products.models import Product
from opennutrilab.products.models import ProductMacronutrient
from opennutrilab.products.services.product_services import ProductAlreadyExistsError
from opennutrilab.products.services.product_services import UnknownMacronutrientError
from opennutrilab.products.services.product_services import create_product
from opennutrilab.products.services.product_services import download_image
from opennutrilab.products.services.product_services import save_image_overwrite
from opennutrilab.products.services.product_services import update_product

if TYPE_CHECKING:
    from django.db.models import FileField
    from django.db.models import Model

BARCODE = "3017620422003"
IMAGE_URL = (
    "https://images.openfoodfacts.org/images/products/301/762/042/2003/front.jpg"
)


def create_payload(**overrides: Any) -> ProductCreate:
    payload: dict[str, Any] = {
        "barcode": BARCODE,
        "name": "Nutella",
        "description": "Spread",
        "nutritional_values": {
            "energy_kj": 2252,
            "macronutrients": [
                {"name": "fat", "amount_g": "30.9"},
                {"name": "sugars", "amount_g": "56.3"},
            ],
        },
        "ingredients": [
            {
                "name": "Sucre",
                "percentage": "56.3",
            },
            {
                "name": "Lait écrémé en poudre",
                "sub_ingredients": [{"name": "lait", "percentage": "8.7"}],
            },
        ],
    }
    payload.update(overrides)
    return ProductCreate.model_validate(payload)


def amounts(product: Product) -> dict[str, Decimal]:
    return dict(
        ProductMacronutrient.objects.filter(product=product).values_list(
            "macronutrient__name", "amount_g"
        )
    )


def ok_image_response(content: bytes = b"jpeg-bytes") -> MagicMock:
    response = MagicMock()
    response.content = content
    response.headers = {"Content-Type": "image/jpeg"}
    return response


@pytest.fixture
def product() -> Product:
    return create_product(create_payload()).product


# -----------------------
# create_product
# -----------------------
@pytest.mark.django_db
def test_create_product_writes_fields_macronutrients_and_ingredient_tree():
    result = create_product(create_payload())
    product = Product.objects.get(pk=BARCODE)

    assert result.product == product
    assert result.image_fetch_failed is False
    assert (product.name, product.description, product.energy_kj) == (
        "Nutella",
        "Spread",
        2252,
    )
    assert amounts(product) == {"fat": Decimal("30.90"), "sugars": Decimal("56.30")}

    roots = Ingredient.objects.filter(product=product, parent=None).order_by("id")
    assert [i.name for i in roots] == ["Sucre", "Lait écrémé en poudre"]
    child = Ingredient.objects.get(product=product, parent=roots[1])
    assert (child.name, child.percentage) == ("lait", Decimal("8.70"))


@pytest.mark.django_db
def test_create_product_refuses_an_existing_barcode(product: Product):
    """
    Product(...).save() with an existing primary key silently UPDATEs, so a
    second create used to overwrite the stored product.
    """
    with pytest.raises(ProductAlreadyExistsError):
        create_product(create_payload(name="Someone else's"))

    assert Product.objects.get(pk=BARCODE).name == "Nutella"


@pytest.mark.django_db
def test_create_product_with_an_unknown_macronutrient_writes_nothing():
    payload = create_payload(
        nutritional_values={
            "energy_kj": 1,
            "macronutrients": [{"name": "unobtainium", "amount_g": "1"}],
        }
    )

    with pytest.raises(UnknownMacronutrientError, match="unobtainium"):
        create_product(payload)

    assert not Product.objects.filter(pk=BARCODE).exists()


@pytest.mark.django_db
def test_create_product_links_references_regardless_of_case():
    """Same rule as the form's "recognized" column, which ignores case."""
    sugar = IngredientRef.objects.create(name="sucre")

    product = create_product(create_payload()).product

    assert Ingredient.objects.get(product=product, name="Sucre").reference == sugar


# -----------------------
# update_product
# -----------------------
@pytest.mark.django_db
def test_update_product_only_touches_what_is_given(product: Product):
    ingredient_ids = set(product.ingredients.values_list("id", flat=True))

    update_product(product, ProductUpdate(name="Renamed"))

    product.refresh_from_db()
    assert product.name == "Renamed"
    assert product.description == "Spread"
    assert amounts(product) == {"fat": Decimal("30.90"), "sugars": Decimal("56.30")}
    # Not recreated: same rows, same ids.
    assert set(product.ingredients.values_list("id", flat=True)) == ingredient_ids


@pytest.mark.django_db
def test_update_product_replaces_the_macronutrient_set(product: Product):
    data = ProductUpdate.model_validate(
        {
            "nutritional_values": {
                "energy_kj": 100,
                "macronutrients": [
                    {"name": "sugars", "amount_g": "0"},
                    {"name": "proteins", "amount_g": "6.3"},
                ],
            }
        }
    )

    update_product(product, data)

    product.refresh_from_db()
    assert product.energy_kj == 100  # noqa: PLR2004
    # fat was left out, so it is removed; 0 g of sugar is kept.
    assert amounts(product) == {"sugars": Decimal("0.00"), "proteins": Decimal("6.30")}


@pytest.mark.django_db
def test_update_product_with_an_empty_macronutrient_list_clears_them(
    product: Product,
):
    data = ProductUpdate.model_validate({"nutritional_values": {"macronutrients": []}})

    update_product(product, data)

    assert amounts(product) == {}


@pytest.mark.django_db
def test_update_product_replaces_the_ingredient_tree_when_given(product: Product):
    data = ProductUpdate.model_validate({"ingredients": [{"name": "Cacao"}]})

    update_product(product, data)

    assert list(product.ingredients.values_list("name", flat=True)) == ["Cacao"]


# -----------------------
# Images
# -----------------------
@pytest.mark.django_db
def test_create_product_downloads_the_photo_named_after_the_barcode():
    with patch(
        "opennutrilab.products.services.product_services.requests.get",
        return_value=ok_image_response(),
    ) as get:
        result = create_product(create_payload(image_url=IMAGE_URL))

    assert get.call_args.args == (IMAGE_URL,)
    assert result.image_fetch_failed is False
    assert result.product.image.name == f"images/products/{BARCODE}.jpg"
    assert result.product.image.read() == b"jpeg-bytes"


@pytest.mark.django_db
def test_failed_photo_download_still_saves_the_product():
    with patch(
        "opennutrilab.products.services.product_services.requests.get",
        side_effect=requests.ConnectTimeout("images host unreachable"),
    ):
        result = create_product(create_payload(image_url=IMAGE_URL))

    assert result.image_fetch_failed is True
    assert Product.objects.filter(pk=BARCODE).exists()
    assert not result.product.image


@pytest.mark.django_db
def test_an_uploaded_photo_wins_over_the_url():
    upload = SimpleUploadedFile("my photo.PNG", b"png-bytes", content_type="image/png")

    with patch("opennutrilab.products.services.product_services.requests.get") as get:
        result = create_product(create_payload(image_url=IMAGE_URL), image=upload)

    get.assert_not_called()
    assert result.product.image.name == f"images/products/{BARCODE}.png"


def test_download_image_refuses_hosts_other_than_openfoodfacts():
    """The schemas reject these URLs too; the function must not rely on it."""
    with (
        patch("opennutrilab.products.services.product_services.requests.get") as get,
        pytest.raises(ValueError, match="Refusing"),
    ):
        download_image("http://redis:6379/", filename="x.jpg")

    get.assert_not_called()


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
