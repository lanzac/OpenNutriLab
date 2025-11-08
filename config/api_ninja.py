from ninja import NinjaAPI

from products.api_ninja import router as products_router

api = NinjaAPI()
api.add_router(prefix="/products/", router=products_router)
