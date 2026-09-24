import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class BusinessException(Exception):
    """业务异常的爹。子类只改默认的 code / status_code，别的都不用重写。

    code 用五位数字，头三位跟着 HTTP 状态码走（40400 对 404，40900 对 409），
    后两位留给同一状态码下更细的区分。这样前端看 code 就知道大概哪一类问题。
    """

    def __init__(
        self,
        message: str,
        *,
        code: int = 40000,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        data: Any = None,
    ) -> None:
        self.message = message
        self.code = code
        self.status_code = status_code
        self.data = data
        # 这一句是为了让日志里打出来的是人话，不然只会打印一个空对象
        super().__init__(message)


class NotFoundException(BusinessException):
    def __init__(self, message: str = "Resource not found.") -> None:
        super().__init__(
            message,
            code=40400,
            status_code=status.HTTP_404_NOT_FOUND,
        )


class PermissionDeniedException(BusinessException):
    def __init__(self, message: str = "Permission denied.") -> None:
        super().__init__(
            message,
            code=40300,
            status_code=status.HTTP_403_FORBIDDEN,
        )


class UnauthorizedException(BusinessException):
    def __init__(self, message: str = "Authentication required.") -> None:
        super().__init__(
            message,
            code=40100,
            status_code=status.HTTP_401_UNAUTHORIZED,
            data=None,
        )


class ConflictException(BusinessException):
    def __init__(self, message: str = "Resource conflict.") -> None:
        super().__init__(
            message,
            code=40900,
            status_code=status.HTTP_409_CONFLICT,
        )


def error_payload(code: int, message: str, data: Any = None) -> dict[str, Any]:
    """出错时的返回体，字段跟成功时那个 ApiResponse 对齐。

    这样前端只要看 code 是不是 0 就知道成没成，不用为"错误"单独写一套解析逻辑。
    """
    return {"code": code, "message": message, "data": data}


def register_exception_handlers(application: FastAPI) -> None:
    """把所有异常统一收口。挂完这些，接口就再也不会漏出 FastAPI 默认的 {"detail": ...}。"""

    @application.exception_handler(BusinessException)
    async def handle_business_exception(
        _request: Request,
        exc: BusinessException,
    ) -> JSONResponse:
        # 业务异常是我们自己主动抛的，属于"预期内"，不用打堆栈日志，免得刷屏
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(exc.code, exc.message, exc.data),
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        # 参数校验失败。FastAPI 默认返 422，格式也跟我们不一样，
        # 所以这里把它转成自己的结构，但把具体的错在哪一项也带上，方便前端定位。
        # jsonable_encoder 是必须的：exc.errors() 里可能带 ValueError 这类
        # 不能直接 JSON 序列化的对象，直接塞进去会报错
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_payload(
                42200,
                "Request validation failed.",
                jsonable_encoder(exc.errors()),
            ),
        )

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        # 走这条的是 FastAPI 自己抛的：404 找不到路由、405 方法不对这一类
        # 注意这里处理的是 starlette 的 HTTPException，不是 fastapi 的那个
        # （fastapi 那个是它的子类，所以挂着一个就能全接住）
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(exc.status_code * 100, str(exc.detail)),
        )

    @application.exception_handler(SQLAlchemyError)
    async def handle_database_error(
        request: Request,
        exc: SQLAlchemyError,
    ) -> JSONResponse:
        # 数据库出错是我们的问题，不是调用方的问题，
        # 所以对外只说"数据库操作失败"，具体原因打日志自己看，别漏给外面
        logger.exception("Database error while handling %s", request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_payload(50001, "Database operation failed."),
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # 兜底。能走到这儿说明有没预料到的异常，一定要打日志（exc_info 会把堆栈带上）
        logger.exception("Unexpected error while handling %s", request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_payload(50000, "Internal server error."),
        )
