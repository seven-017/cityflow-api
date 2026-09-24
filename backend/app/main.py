from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    """把整个应用装出来，返回一个 FastAPI 实例。

    用工厂函数而不是模块级直接 `app = FastAPI()`，好处有三个：
    1. 测试的时候能造一个"配置不一样"的应用（比如连测试库），互不干扰
    2. uvicorn --reload 重载时不会带着上一次的全局状态
    3. 配置是"进来的时候读"的，不是"import 的时候就冻住"的
    """
    settings = get_settings()

    # 日志得在应用建出来之前配好，不然启动过程本身的日志就漏了
    configure_logging(settings)

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.app_debug,
        docs_url="/docs",
        redoc_url="/redoc",
        # openapi.json 放到 /api/v1 下面，跟接口待在一块儿，别散落在根路径
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    )

    # 前端在 5173 跑，后端在 8000，属于跨域，不放行的话浏览器直接拦掉
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 异常处理器要在挂路由之前注册好，顺序反了的话前面已经挂上去的路由
    # 用的还是默认处理方式
    register_exception_handlers(application)
    application.include_router(api_router, prefix=settings.api_v1_prefix)

    return application


# uvicorn 找的就是这个模块级变量：`uvicorn app.main:app`
app = create_app()
