from fastapi import APIRouter

from app.api.v1.routers import assets, auth, health, system

# 所有 v1 接口的总入口，新增一个模块就在这儿挂一行
api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(assets.router, prefix="/assets", tags=["assets"])
