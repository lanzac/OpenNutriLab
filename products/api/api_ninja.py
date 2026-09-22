from ninja import Router

from .api_ninja_crud import router as crud_router

router = Router()

router.add_router(prefix="/", router=crud_router)
