from django.urls import path
from django.urls.resolvers import URLPattern

from .views import FoodCreateView
from .views import FoodDeleteView
from .views import FoodEditView
from .views import FoodListView

urlpatterns: list[URLPattern] = [
    path(route="foods/", view=FoodListView.as_view(), name="list_foods"),
    path(route="foods/new/", view=FoodCreateView.as_view(), name="create_food"),
    path(route="foods/<str:pk>/edit/", view=FoodEditView.as_view(), name="edit_food"),
    path(
        route="foods/<str:pk>/delete/",
        view=FoodDeleteView.as_view(),
        name="delete_food",
    ),
]
