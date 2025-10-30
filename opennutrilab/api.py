# main_app/api.py
from ninja import NinjaAPI

from products.api import router as products_router

api = NinjaAPI()
api.add_router(prefix="/product/", router=products_router)
