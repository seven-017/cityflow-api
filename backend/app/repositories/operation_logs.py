from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import OperationLog


class OperationLogRepository:
    """操作日志：只写不改。所以这里没有 update / delete，
    唯一能改状态的方式是再加一条新记录（审计日志的常规做法）。
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(
        self,
        *,
        user_id: int | None,
        operation: str,
        module: str,
        result: str,
        target_type: str | None = None,
        target_id: str | None = None,
        request_method: str | None = None,
        request_path: str | None = None,
        detail: str | None = None,
        ip_address: str | None = None,
    ) -> OperationLog:
        # 注意：这里只 add，不 commit。提交的时机交给调用的 service 决定 ——
        # 因为经常要"业务改动 + 日志"一起成功或一起失败，分成两次提交就对不上了
        operation_log = OperationLog(
            user_id=user_id,
            operation=operation,
            module=module,
            target_type=target_type,
            target_id=target_id,
            request_method=request_method,
            request_path=request_path,
            result=result,
            detail=detail,
            ip_address=ip_address,
        )
        self.db.add(operation_log)
        return operation_log

    def list_logs(self, offset: int, limit: int) -> list[OperationLog]:
        statement = (
            select(OperationLog)
            .options(joinedload(OperationLog.user))
            # 日志看最近的，所以按 id 倒序
            .order_by(OperationLog.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.execute(statement).scalars().all())

    def count_logs(self) -> int:
        return int(self.db.execute(select(func.count(OperationLog.id))).scalar_one())
