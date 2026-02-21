from ninja import Router

from .api_ninja_crud import router as crud_router
from .api_ninja_forms_deprecated import router as forms_router_deprecated
from .openfoodfacts.api_ninja_fetch_product import router as off_fetch_router

router = Router()

router.add_router(prefix="/", router=crud_router)
router.add_router(prefix="/off", router=off_fetch_router)
router.add_router(prefix="/off", router=forms_router_deprecated)
