from fastapi import APIRouter

from app.api.v1.routers import assets, auth, health, system, work_orders

# 所有 v1 接口的总入口，新增一个模块就在这儿挂一行
api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(assets.router, prefix="/assets", tags=["assets"])
# URL 里用短横线（/work-orders）是 REST 的老习惯，虽然权限点写的是 work_order:read。
# 一个用横线一个用下划线看着别扭，但两边各自都是常见写法，就不强行统一了
api_router.include_router(
    work_orders.router, prefix="/work-orders", tags=["work-orders"]
)
