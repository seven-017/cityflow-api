from enum import StrEnum


class RoleCode(StrEnum):
    """四个角色。用 StrEnum 是为了它既能当字符串比，又不会被拼错 ——
    写错字母是 AttributeError，不会悄悄变成另一个值。
    """

    ADMIN = "ADMIN"
    DISPATCHER = "DISPATCHER"
    ENGINEER = "ENGINEER"
    VIEWER = "VIEWER"


class PermissionCode(StrEnum):
    """权限点，格式是 资源:动作。跟库里 permissions 表那 13 行一一对应。"""

    ASSET_READ = "asset:read"
    WORK_ORDER_READ = "work_order:read"
    WORK_ORDER_CREATE = "work_order:create"
    WORK_ORDER_UPDATE = "work_order:update"
    WORK_ORDER_ASSIGN = "work_order:assign"
    LABOR_READ = "labor:read"
    LABOR_CREATE = "labor:create"
    TRANSACTION_READ = "transaction:read"
    DASHBOARD_READ = "dashboard:read"
    ANALYTICS_READ = "analytics:read"
    USER_MANAGE = "user:manage"
    ROLE_MANAGE = "role:manage"
    OPERATION_LOG_READ = "operation_log:read"
