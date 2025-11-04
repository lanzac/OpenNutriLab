from django.urls import path
from django.urls.resolvers import URLPattern

from .views import ProductCreateView
from .views import ProductDeleteView
from .views import ProductEditView
from .views import ProductListView
from .views import ProductPlotDataView

urlpatterns: list[URLPattern] = [
    path(route="products/", view=ProductListView.as_view(), name="list_products"),
    path(
        route="products/new/", view=ProductCreateView.as_view(), name="create_product"
    ),
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
    path(
        route="plot-data/", view=ProductPlotDataView.as_view(), name="product_plot_data"
    ),
]
