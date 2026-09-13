from fastapi import APIRouter

from .routes import batches, compare, dashboard, groups, images, jobs

api_router = APIRouter()
api_router.include_router(dashboard.router)
api_router.include_router(compare.router)
api_router.include_router(images.router)
api_router.include_router(batches.router)
api_router.include_router(groups.router)
api_router.include_router(jobs.router)

