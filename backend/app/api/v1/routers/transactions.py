from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permissions
from app.core.permissions import PermissionCode
from app.models import User
from app.schemas.common import ApiResponse
from app.schemas.transactions import TransactionDetail
from app.services.transactions import TransactionService

router = APIRouter()


@router.get("/{transaction_id}", response_model=ApiResponse[TransactionDetail])
def get_transaction(
    transaction_id: int,
    db: Annotated[Session, Depends(get_db)],
    # 权限闸门。名字前面加下划线是因为这个参数我们自己不用，
    # 纯粹为了让那个依赖跑起来 —— 它跑到了，权限就是查过了。
    #
    # 用的是 transaction:read，库里四个角色都有（跟业务规则那张表一致：
    # Transactions 那一列全是"读"，连 ADMIN 也只有读 —— 物料交易是历史数据，
    # 平台不允许改，所以没有 transaction:create / update 这种权限点）
    _: Annotated[
        User, Depends(require_permissions(PermissionCode.TRANSACTION_READ))
    ],
    # 明细的游标。不传就是第一页，传上一页 detail_meta.next_cursor 就往下翻。
    # 名字前面加 detail_ 前缀，是因为这个接口有两个"东西"：
    # 一个是被路径定死的交易单（只有一张，不需要分页），
    # 一个是它的明细（可能几千行，需要分页）。
    # 不加前缀的话，一个光秃秃的 after_id 说不清是在翻什么
    detail_after_id: int | None = Query(None, ge=1),
    # 上限 100 是跟别的列表接口对齐的。默认 20 而不是更大，是因为
    # 71.5% 的单明细本来就只有 1 行，默认给大了纯属浪费
    detail_limit: int = Query(20, ge=1, le=100),
) -> ApiResponse[TransactionDetail]:
    # transaction_id 是路径参数，FastAPI 自己会转成 int。传个 abc 进来会甩 422
    return ApiResponse(
        data=TransactionService(db).get_transaction(
            transaction_id=transaction_id,
            detail_after_id=detail_after_id,
            detail_limit=detail_limit,
        )
    )
