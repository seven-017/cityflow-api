from fastapi import APIRouter

from app.api.v1.routers import (
    assets,
    auth,
    dashboard,
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
# 现在是读 + 写两个接口：GET /labor（列表）、POST /labor（录一条工时）。
# 写接口那个权限点 labor:create 跟读是分开的，库里只有 ADMIN 和 ENGINEER 有
api_router.include_router(labor.router, prefix="/labor", tags=["labor"])
# transactions 是物料交易（领了什么料、从哪个库到哪个库）。
# 跟 labor 不一样的是它有两层：交易头 + 逐行物料明细，所以前缀用复数。
# 现在挂了两个：GET /transactions（列表）和 GET /transactions/{id}（详情）
api_router.include_router(
    transactions.router, prefix="/transactions", tags=["transactions"]
)
# dashboard 是首页那一页的聚合。跟前面几个不一样的地方：它不翻页、不带过滤，
# 一次把整页要的数都算出来。也是整个项目唯一走缓存的读接口 ——
# 冷启动 5.96 秒，缓存命中之后不碰数据库。为什么是进程内缓存不是 Redis，
# 看 core/cache.py 里那一整段
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
