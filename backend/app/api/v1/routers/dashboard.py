from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permissions
from app.core.permissions import PermissionCode
from app.models import User
from app.schemas.common import ApiResponse
from app.schemas.dashboard import DashboardOverview
from app.services.dashboard import DashboardService

router = APIRouter()


# 这里没写路径参数和查询参数，一个都没有 —— 不是漏了。
# api.md 里 GET /dashboard/overview 底下只有一句「返回：…」，
# 参数是隔壁 GET /analytics/overview 才有的（date_from / date_to / asset_type / work_type）。
# 两个接口名字长得像，但一个是"现在怎么样"（不带条件），
# 一个是"某段时间、某类资产怎么样"（带条件）。别看着像就把参数抄过来。
#
# 路径写 /overview，前缀 /dashboard 在 api/v1/router.py 里挂 —— 拼起来才是文档上的
# /api/v1/dashboard/overview
@router.get("/overview", response_model=ApiResponse[DashboardOverview])
def get_dashboard_overview(
    db: Annotated[Session, Depends(get_db)],
    # 权限闸门。名字前面加下划线是因为这个参数我们自己不用，
    # 纯粹为了让那个依赖跑起来 —— 它跑到了，权限就是查过了
    #
    # 用的是 dashboard:read，库里四个角色都有。这跟业务规则那张 RBAC 表对得上：
    # 「统计」那一列 ADMIN / DISPATCHER / VIEWER 写的是"是"，ENGINEER 写的是
    # "Dashboard" —— 意思就是四个角色都看得到这个页面，只是叫法不同。
    # 所以这个接口没有"谁看不了"的分支，跟写接口那种要分角色的地方不一样。
    _: Annotated[
        User, Depends(require_permissions(PermissionCode.DASHBOARD_READ))
    ],
) -> ApiResponse[DashboardOverview]:
    # 这个接口的耗时是两段的：第一次要好几秒（5.96 秒，五个聚合），
    # 之后 5 分钟内再来是毫秒级（走缓存，不碰数据库）。
    # 具体数字和那份缓存的设计写在 schemas/dashboard.py 和 core/cache.py 里
    return ApiResponse(data=DashboardService(db).get_overview())
