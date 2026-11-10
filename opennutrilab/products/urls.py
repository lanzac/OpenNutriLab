from django.urls import path
from django.urls.resolvers import URLPattern

from .views import OffLookupView
from .views import ProductCreateView
from .views import ProductDeleteView
from .views import ProductEditView
from .views import ProductListView
from .views import ReadLabelView
from .views import SearchOffView
from .views import SendLabelView

urlpatterns: list[URLPattern] = [
    path(route="products/", view=ProductListView.as_view(), name="list_products"),
    path(
        route="products/new/", view=ProductCreateView.as_view(), name="create_product"
    ),
    path(route="products/read-label/", view=ReadLabelView.as_view(), name="read_label"),
    path(route="products/search-off/", view=SearchOffView.as_view(), name="search_off"),
    path(route="products/lookup-off/", view=OffLookupView.as_view(), name="lookup_off"),
    path(route="products/send-label/", view=SendLabelView.as_view(), name="send_label"),
    path(
        route="products/<str:pk>/edit/",
        view=ProductEditView.as_view(),
        name="edit_product",
    ),
    path(
        route="products/<str:pk>/delete/",
        view=ProductDeleteView.as_view(),
        name="delete_product",
    ),
]
