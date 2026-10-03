from django.apps import AppConfig


class ProductsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "opennutrilab.products"
    # Kept from when the app lived at the repository root: the database
    # tables and migrations are named after it.
    label = "products"

    def ready(self):
        # Imported for its side effect: registering the signal receivers.
        import opennutrilab.products.signals  # noqa: F401  # pyright: ignore[reportUnusedImport]
