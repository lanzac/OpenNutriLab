from django.urls import path
from .views import (
    FoodListView, FoodCreateView, FoodEditView, FoodDeleteView
)

urlpatterns = [
    path('foods/', FoodListView.as_view(), name='list_foods'),
    path('foods/new/', FoodCreateView.as_view(), name='create_food'),
    path('foods/<str:pk>/edit/', FoodEditView.as_view(), name='edit_food'),
    path('foods/<str:pk>/delete/', FoodDeleteView.as_view(), name='delete_food'),
]