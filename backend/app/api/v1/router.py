from fastapi import APIRouter

from app.api.v1.routers import (
    assets,
    auth,
    health,
    labor,
    system,
    transactions,
    work_orders,
)

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
# labor 是工时（谁来干了多长时间、多少钱）。文档里路径就是 /labor，没有横线。
# 这条线是从 AMPS 原始数据映射过来的，跟 assets 一样只有读接口 ——
# 平台自己记工时的写接口（labor:create 那个权限点）还没做
api_router.include_router(labor.router, prefix="/labor", tags=["labor"])
# transactions 是物料交易（领了什么料、从哪个库到哪个库）。
# 跟 labor 不一样的是它有两层：交易头 + 逐行物料明细，所以前缀用复数。
# 这一版只挂了详情（GET /transactions/{id}），列表接口还没做
api_router.include_router(
    transactions.router, prefix="/transactions", tags=["transactions"]
)
