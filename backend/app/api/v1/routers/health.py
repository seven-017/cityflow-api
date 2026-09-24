from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.schemas.common import ApiResponse

router = APIRouter()


class HealthData(BaseModel):
    # Literal["ok"] 的意思是"这个字段只允许是字符串 ok"，写别的一律校验不过
    status: Literal["ok"]
    service: str
    environment: str
    version: str


class DatabaseHealthData(BaseModel):
    status: Literal["ok"]
    database: Literal["mysql"]


@router.get("", response_model=ApiResponse[HealthData])
def health_check() -> ApiResponse[HealthData]:
    """活着吗。只回答服务自身的情况，不碰数据库。

    单独留这么一个"不碰外部依赖"的接口，是用来给负载均衡 / 监控探活的：
    太重的检查会把探活本身拖垮。
    """
    settings = get_settings()
    return ApiResponse(
        data=HealthData(
            status="ok",
            service=settings.app_name,
            environment=settings.app_env,
            version=settings.app_version,
        )
    )


@router.get(
    "/database",
    response_model=ApiResponse[DatabaseHealthData],
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Database unavailable"}},
)
def database_health_check(
    db: Annotated[Session, Depends(get_db)],
) -> ApiResponse[DatabaseHealthData]:
    """再单独探一下数据库通不通。

    为什么不用 health_check 顺手查一下？因为"服务活着"和"数据库活着"
    是两件事：数据库挂了的时候接口还能返回 503 告诉你是数据库的问题，
    比整个服务没响应好排查得多。
    """
    try:
        # 最轻的一条查询，只为了确认连接真的能用
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        # from exc 是保留原始异常的因果链，日志里能看到根因，别丢掉
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection is unavailable.",
        ) from exc

    return ApiResponse(data=DatabaseHealthData(status="ok", database="mysql"))
