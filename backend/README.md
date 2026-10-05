# CityFlow 后端

FastAPI 服务。项目整体介绍、数据规模、接口清单和性能设计在上一层 README，这里只讲这份代码本身：怎么装、怎么改、改的时候守哪些规矩。

## 装起来

```powershell
uv sync
Copy-Item .env.example .env    # 然后改 DATABASE_URL 指向你的 MySQL
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Swagger 在 `http://127.0.0.1:8000/docs`。

注意 `.env.example` 里的端口写的是 3306（通用情况），开发机上如果 MySQL 跑在别的端口，改 `.env` 那一行就行，不要动 `core/config.py` 里的默认值。默认值放通例，实情放 `.env`。

## 目录

```text
app/
  api/
    deps.py          依赖注入：当前用户、分页参数、权限校验
    v1/router.py     总入口，新增一个模块在这儿挂一行
    v1/routers/      各模块路由
  core/
    config.py        配置项，全部走 pydantic-settings
    security.py      密码哈希、JWT 签发与校验
    permissions.py   角色与权限点枚举
    work_order_status.py  工单状态机
    work_order_sla.py     SLA 与优先级
    data_sources.py  双数据源枚举
    exceptions.py    业务异常 + 统一异常处理器
    cache.py         进程内 TTL 缓存
    logging.py       日志配置
  models/            SQLAlchemy 表定义
  schemas/           Pydantic 请求与响应模型
  repositories/      SQL 查询，只有这一层能写 select()
  services/          业务规则与缓存编排
  db/                engine、session、Base
alembic/versions/    数据库迁移
tests/               pytest 测试
docs/                设计文档
```

## 分层规矩

四层单向依赖：`routers -> services -> repositories -> models`。两条不能破：

1. 只有 `repositories/` 里能出现 `select()`。service 要数据就调 repository 方法，别自己拼查询。理由很实在：查询散在 service 里之后，想给某个查询加索引调整、想统计谁在扫大表，都找不到地方下手
2. `services/` 之间不许互相 import。两边都要用的东西，抽到 `core/`（纯逻辑，比如状态机、数据源枚举）或 `repositories/sql_helpers.py`（SQL 片段）

第二条有实例可查：双数据源那两个常量原本写死在 `services/work_orders.py` 里，后来工时的写接口也要用同一对值，而工时不该反过来 import 工单模块，于是挪到了 `core/data_sources.py`。

repository 方法返回 `NamedTuple` 而不是 ORM 对象。原因是查出来的结果常常是聚合值或者跨表的几列，硬塞进某个 ORM 类里不合适；NamedTuple 拿起来就能用，也不用担心 session 关闭后的属性访问问题。

## 加一个接口要碰哪些文件

假设要加一个「查某个工单下的全部工时」：

1. `repositories/labor.py` —— 加一个查询方法，返回 NamedTuple。只写 SQL，不做业务判断
2. `schemas/labor.py` —— 加响应模型。字段类型要跟模型上的可空性对齐，别把可空列写成必填
3. `services/labor.py` —— 加业务方法。要不要先校验工单存在、要不要查缓存、权限够不够，都在这一层判断
4. `api/v1/routers/labor.py` —— 加路由函数。声明依赖（当前用户、权限点）、调 service、包进统一响应
5. `app/api/v1/router.py` —— 只有新增一个模块时才需要在这里加一行，往已有模块加接口不用动

权限点通过依赖注入挂上去，形如 `Depends(require_permission(PermissionCode.LABOR_READ))`。校验发生在进业务逻辑之前，业务代码里不用再写一遍 if。

## 环境变量

配置项在 `app/core/config.py`，从 `.env` 读，也能被真实环境变量覆盖。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_NAME` | `CityFlow API` | Swagger 标题 |
| `APP_ENV` | `development` | `development` / `test` / `production` |
| `APP_DEBUG` | `false` | 开了打 DEBUG 日志 |
| `API_V1_PREFIX` | `/api/v1` | 所有接口的公共前缀 |
| `DATABASE_URL` | 指向 127.0.0.1:3306 | SQLAlchemy 连接串 |
| `CORS_ORIGINS` | 5173 两个地址 | 允许跨域的前端来源 |
| `SQL_ECHO` | `false` | 把每条 SQL 打到日志，查慢查询时才开 |
| `MYSQL_LOCAL_INFILE` | `true` | 允许 `LOAD DATA LOCAL INFILE` |
| `JWT_SECRET_KEY` | 开发用明文 | 上线必须换成真密钥，泄露了别人能伪造任意 token |
| `JWT_ALGORITHM` | `HS256` | 对称加密，单服务够用 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | token 有效期 |
| `DASHBOARD_CACHE_TTL_SECONDS` | `300` | Dashboard 聚合缓存时长 |
| `DASHBOARD_MAX_CONCURRENT_AGGREGATIONS` | `2` | 同时真跑的聚合数上限 |
| `DASHBOARD_TREND_WINDOW_MONTHS` | `12` | 趋势图与平均周期看最近几个月 |

最后四项的取值理由都写在 `config.py` 的注释里，尤其是 `DASHBOARD_TREND_WINDOW_MONTHS = 12`——它是量出来的边界，往上加一格性能会塌方。

## 数据库迁移

```powershell
uv run alembic upgrade head              # 升到最新
uv run alembic downgrade -1              # 回退一步
uv run alembic revision -m "描述"        # 生成一个空迁移
uv run alembic current                   # 当前版本
```

改模型的流程是：改 `app/models/`，然后手写一个迁移文件放进 `alembic/versions/`。命名跟着现有文件走（`日期_序号_描述.py`）。迁移里只放结构变更，不放种子数据。

索引不是随手加的。加之前先 `EXPLAIN` 看一眼打算给谁用：有些列选择性太差（比如 `status`，九成以上的行都是同一个值），建了索引优化器也不会走，白占空间还拖慢写入。

## 测试

```powershell
uv run pytest -v
```

`pyproject.toml` 里那行 `pythonpath = ["."]` 是必需的，删了 `import app` 会直接 `ModuleNotFoundError`——pytest 默认只把测试文件所在目录插进 `sys.path`，从 `tests/` 那个位置看不到挂在 `backend/` 下的 `app` 包。

新加测试时注意一件事：期望值要照着业务规则写，别照着实现逻辑抄。抄实现等于把代码再念一遍，真出了 bug 它跟代码一起错，测了等于没测。

## 代码风格

- 注释写成人话，像在跟同事解释，不要写成技术文档。允许出现「说白了」「千万别」「其实」这种口气
- 注释里不用 markdown 的加粗，要强调就换「」
- 代码里不放表情符号
- 涉及性能取舍、踩过的坑、为什么选这个方案，都写在注释里。`docs/` 那三份记的是规则和规格（要求做什么、本仓库有没有做），注释记的是推导和实测数字（为什么这么做、量出来多少），两边分工别混
