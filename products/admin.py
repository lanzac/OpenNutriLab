from django.contrib import admin

from .models import Macronutrient
from .models import Product
from .models import ProductMacronutrient
from .models import ProductVitamin
from .models import Vitamin

# Register your models here.

admin.site.register(
    [Product, Macronutrient, ProductMacronutrient, Vitamin, ProductVitamin]
)
