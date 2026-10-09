from django.urls import path
from django.urls.resolvers import URLPattern

from .views import NeedsView

urlpatterns: list[URLPattern] = [
    path(route="needs/", view=NeedsView.as_view(), name="nutrition_needs"),
]
