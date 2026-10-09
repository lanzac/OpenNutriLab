from django.contrib import admin

from .models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin[Profile]):
    list_display = ("user", "sex", "birth_year", "height", "weight", "activity_level")
    list_select_related = ("user",)
