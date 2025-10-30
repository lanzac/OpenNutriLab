# main_app/api.py
from ninja import NinjaAPI

from foods.api import router as foods_router

api = NinjaAPI()
api.add_router(prefix="/product/", router=foods_router)
