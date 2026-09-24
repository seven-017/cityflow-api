from enum import StrEnum


class RoleCode(StrEnum):
    """四个角色。写成 StrEnum 是为了它能当字符串用（进 JSON、比大小都行），
    又不会被拼错 —— 敲错一个字母是 AttributeError，不是"悄悄变成另一个值"。
    """

    ADMIN = "ADMIN"          # 管理员，什么都能干
    DISPATCHER = "DISPATCHER"  # 调度员，能建工单能分派，但不能管人和权限
    ENGINEER = "ENGINEER"      # 工程师，只能处理分给自己的工单、报工时
    VIEWER = "VIEWER"          # 只读，看数据用


class PermissionCode(StrEnum):
    """权限点，格式是 `资源:动作`。共 13 个，对应库里 permissions 表的 13 行。"""

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


# 每个权限点的「中文说明 + 属于哪个模块」。种子脚本灌 permissions 表时按这份定义走，
# 好处是"权限清单"只有这一个地方，不会出现代码里加了权限、库里却没这行的情况
PERMISSION_DEFINITIONS = {
    PermissionCode.ASSET_READ: ("View assets", "asset"),
    PermissionCode.WORK_ORDER_READ: ("View work orders", "work_order"),
    PermissionCode.WORK_ORDER_CREATE: ("Create work orders", "work_order"),
    PermissionCode.WORK_ORDER_UPDATE: ("Update work orders", "work_order"),
    PermissionCode.WORK_ORDER_ASSIGN: ("Assign work orders", "work_order"),
    PermissionCode.LABOR_READ: ("View labor records", "labor"),
    PermissionCode.LABOR_CREATE: ("Create labor records", "labor"),
    PermissionCode.TRANSACTION_READ: ("View material transactions", "transaction"),
    PermissionCode.DASHBOARD_READ: ("View dashboard statistics", "dashboard"),
    PermissionCode.ANALYTICS_READ: ("View analytics", "analytics"),
    PermissionCode.USER_MANAGE: ("Manage users", "system"),
    PermissionCode.ROLE_MANAGE: ("Manage roles", "system"),
    PermissionCode.OPERATION_LOG_READ: ("View operation logs", "system"),
}


# 纯看的权限，单独拎出来，VIEWER 角色整个就用这一份
READ_ONLY_PERMISSIONS = frozenset(
    {
        PermissionCode.ASSET_READ,
        PermissionCode.WORK_ORDER_READ,
        PermissionCode.LABOR_READ,
        PermissionCode.TRANSACTION_READ,
        PermissionCode.DASHBOARD_READ,
        PermissionCode.ANALYTICS_READ,
    }
)


# 「角色 -> 权限」的默认映射。注意：**真正判权限的时候不读这里**，
# 这里只用来灌种子数据。运行时读的是库里 user_roles / role_permissions 那两张关联表，
# 这样管理员才能在界面上改角色权限，而不用改代码重新部署
ROLE_PERMISSIONS: dict[RoleCode, frozenset[PermissionCode]] = {
    # ADMIN 拿全集：直接对枚举本身取 frozenset，以后新增权限点自动包含，不用来改这一行
    RoleCode.ADMIN: frozenset(PermissionCode),
    RoleCode.DISPATCHER: frozenset(
        {
            PermissionCode.ASSET_READ,
            PermissionCode.WORK_ORDER_READ,
            PermissionCode.WORK_ORDER_CREATE,
            PermissionCode.WORK_ORDER_UPDATE,
            PermissionCode.WORK_ORDER_ASSIGN,
            PermissionCode.LABOR_READ,
            PermissionCode.TRANSACTION_READ,
            PermissionCode.DASHBOARD_READ,
            PermissionCode.ANALYTICS_READ,
        }
    ),
    RoleCode.ENGINEER: frozenset(
        {
            PermissionCode.ASSET_READ,
            PermissionCode.WORK_ORDER_READ,
            PermissionCode.WORK_ORDER_UPDATE,
            PermissionCode.LABOR_READ,
            PermissionCode.LABOR_CREATE,
            PermissionCode.TRANSACTION_READ,
            PermissionCode.DASHBOARD_READ,
        }
    ),
    RoleCode.VIEWER: READ_ONLY_PERMISSIONS,
}
