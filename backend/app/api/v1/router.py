from fastapi import APIRouter

from app.api.v1.routers import health

# 这里是所有 v1 接口的总入口：每新增一个模块，就在这儿挂一行。
# 目前只有 health，资产 / 工单 / 工时那些等各自的 service 写完再加，
# 加早了会 import 不到东西，服务直接起不来。
api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
