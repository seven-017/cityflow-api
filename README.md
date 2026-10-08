# CityFlow

CityFlow 是一个城市公园资产与维修工单的后端服务，数据来自纽约市公园管理局（NYC Parks）的 AMPS 开放数据集。

它做四件事：把官方公开的历史数据整理进 MySQL、在上面提供带分页和筛选的只读查询、允许平台用户自己新建并流转工单（含工时与物料记录）、以及给首页提供一整套聚合统计。鉴权走 JWT，权限走四级 RBAC，历史数据和平台自己产生的数据在库层隔离。

技术栈是 FastAPI + SQLAlchemy 2.0 + MySQL 8，代码分四层，共 21 条路由。

## 业务背景

公园里的长椅、灯杆、喷泉、游乐设施这些资产会被反复维修。这批数据里最早的工单是 2000 年 1 月，最近的是 2026 年 9 月，二十多年积累出一套完整的运维记录：

- 一次维修对应一张工单，工单在报修、分派、处理、完成、关闭之间流转，也可能被驳回
- 干活的人报工时：谁、哪天、干了几小时、什么工种、单价多少
- 维修要从仓库领料，一笔领料下面挂着逐行物料明细

AMPS 数据集就是这套流程的原始记录。CityFlow 把它变成一个能翻页、能筛选、能写操作的 HTTP 服务。

## 数据规模

下面这张表是开发库里 `COUNT(*)` 的实测值（2026-10-05），不是估算：

| 表 | 行数 | 说明 |
| --- | ---: | --- |
| `assets` | 148,423 | 公园资产 |
| `work_orders` | 2,220,853 | 历史工单 |
| `work_order_labor` | 3,202,020 | 工时记录 |
| `transactions` | 752,746 | 物料交易头 |
| `transaction_details` | 2,290,091 | 交易逐行明细 |
| 合计 | 8,614,133 | |

另有几张平台自用的表：`users`(4)、`roles`(4)、`permissions`(13)、`role_permissions`(35)、`operation_logs`(637)，以及记录工单流转的 `work_order_status_history` 和 `work_order_processing_records`。

`information_schema` 报的 `TABLE_ROWS` 是采样估算，跟实际差着几万行（比如 `work_orders` 会报成 2,158,704），所以上表取自 `COUNT(*)`。

## 双数据源隔离

五张官方表里的每一行都带一个 `data_source` 列，只有两个合法取值：

| 取值 | 含义 | 能否修改 |
| --- | --- | --- |
| `REAL_PUBLIC` | 从官方数据集导入的历史记录 | 只读，写操作会被拦下 |
| `SYNTHETIC_PLATFORM` | 平台用户自己建的记录 | 可读写 |

这么分的理由是历史数据不该被改：它是对外的既成事实，一旦允许改，统计口径和溯源就全乱了。所以平台新建的工单、工时走独立编号（工单是 `PF-` 加 12 位十六进制），从数据源这一层就跟历史数据分开。

有一个地方容易踩坑：`data_source` 在模型上带默认值 `REAL_PUBLIC`，写接口忘了显式指定的话，数据库会默默把平台自己录的记录标成官方数据，然后这条记录就再也改不动了，而且全程不报错。所以每个写接口都显式写出目标数据源。

## 核心能力

- 资产查询：游标分页的列表 + 详情页
- 工单管理：列表、详情、创建，以及六个状态之间的流转（分派、开始、完成、关闭、驳回）
- 工单状态机：状态转移表 + 动作权限，非法流转返回 409 而不是 500
- 处理记录与状态历史：工单的每一步流转都留痕
- 工时：查询与录入，按工程师、工种、日期筛选
- 物料交易：交易头 + 逐行明细，两层结构分别展示
- 首页聚合：十项指标 + 九个图表，走进程内 TTL 缓存
- RBAC：4 个角色、13 个权限点，按 资源:动作 的格式定义
- SLA：平台工单按优先级 P1\~P4 给出目标完成时间，历史工单不伪造 SLA
- 操作日志：登录、写操作、权限变更全部记录
- 统一响应：所有接口共用 `{code, message, data}` 结构，出错也不会漏出框架默认格式

## 技术栈

| 类别 | 选型 |
| --- | --- |
| 语言 | Python 3.13 |
| Web 框架 | FastAPI 0.141 |
| ORM | SQLAlchemy 2.0（同步） |
| 数据库 | MySQL 8 |
| 迁移 | Alembic |
| 驱动 | PyMySQL |
| 配置 | pydantic-settings |
| 认证 | PyJWT + Argon2（pwdlib） |
| 测试 | pytest |
| 包管理 | uv |

## 分层架构

```text
HTTP 请求
  -> Router        解析参数、装配依赖、调用 service
    -> Service     业务规则：状态机、权限、SLA、缓存编排
      -> Repository  拼 SQL，返回 NamedTuple
        -> Model    SQLAlchemy 表定义
          -> MySQL 8
```

四层是单向依赖的，两条硬规矩：

- 只有 repository 层允许出现 `select()`。service 想查数据就得调 repository，不许自己拼查询
- service 之间不许互相 import。同一个工具函数两边都要用，就抽到 `core/` 或 `repositories/sql_helpers.py`

第二条不是洁癖。一旦 service 互引，调用链会变成网状，改一个函数的返回值要顺着两边都看一遍。抽公共件虽然多写一个文件，但依赖关系始终是一棵树。

## 工单状态机

六个状态、五个动作，允许的转移是写死的一张表：

```text
PENDING ──ASSIGN──> ASSIGNED ──START──> IN_PROGRESS ──COMPLETE──> COMPLETED ──CLOSE──> CLOSED
   │                   │
   └──REJECT──> REJECTED └──REJECT──> REJECTED
```

- `REJECTED` 和 `CLOSED` 是终点，出去了就回不来（写成空的集合，而不是干脆不写这个键——后者会让人以为是漏填了）
- `COMPLETED` 不算终点，它后面还有一步 `CLOSED`
- 工程师只能执行 START 和 COMPLETE，分派、关闭、驳回归调度和管理

这里有两层闸门，缺一层就是漏洞：一层是权限点（`work_order:update` 管你能不能碰工单，四个角色里三个都有），另一层是动作归属（能碰工单的人里，哪个动作归谁）。

非法流转返回 409 而不是 500。这不是服务器坏了，是调用方想做的事情跟这张单当前的状态对不上（比如想驳回一个已经完成的单），得让调用方知道是它点错了地方。

## 项目结构

```text
backend/
  app/
    api/v1/
      deps.py            依赖注入：当前用户、分页参数、权限校验
      router.py          所有 v1 接口的总入口
      routers/           各模块的路由（assets / auth / dashboard / health /
                         labor / system / transactions / work_orders）
    core/                配置、安全、权限点、状态机、SLA、异常、缓存、日志、数据源
    models/              SQLAlchemy 表定义
    schemas/             Pydantic 请求与响应模型
    repositories/        SQL 查询，只有这一层能写 select()
    services/            业务规则与缓存编排
    db/                  engine、session、Base
  alembic/versions/      数据库迁移
  tests/                  pytest 测试
  docs/                  设计文档（规格，以及每处跟实际做法的出入）
```

## 设计文档

`backend/docs/` 下三份：

- `business-rules.md` —— 数据源规则、工单状态机、SLA、RBAC、空值处理
- `architecture.md` —— 分层、认证授权、查询与性能、并发
- `api.md` —— 接口规格

这三份是动手写之前定的规格，所以跟最终实现有出入 —— 没做的接口、改了形的参数、发现规格本身没写全的地方，都在里面标了「本仓库」。要看当前实际有哪些接口，以 `app.openapi()["paths"]` 为准，代码自己生成的不会过期。

## 本地启动

### 环境要求

- Python 3.13
- MySQL 8
- uv

### 准备数据库

需要一个装好 AMPS 数据集的 MySQL 实例。数据集本身不随仓库分发（原始 CSV 约 2.2 GB），需要自行导入。

```sql
CREATE DATABASE cityflow
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;
```

### 启动后端

```powershell
cd backend
Copy-Item .env.example .env
```

编辑 `.env`，把 `DATABASE_URL` 指向你的实例，然后：

```powershell
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

- 服务地址：`http://127.0.0.1:8000`
- Swagger 文档：`http://127.0.0.1:8000/docs`
- OpenAPI JSON：`http://127.0.0.1:8000/api/v1/openapi.json`

数据库迁移负责建表。四个开发账户和它们的角色权限已经在库里，见下一节。

## 默认开发账户

密码统一为 `CityFlow@123`：

| 用户名 | 角色 | 能做什么 |
| --- | --- | --- |
| `admin` | `ADMIN` | 全部权限，含用户和角色管理 |
| `dispatcher` | `DISPATCHER` | 工单全流程 + 分派，含分析报表 |
| `engineer` | `ENGINEER` | 只看工单和资产，能开始和完成自己手上的单，能录工时 |
| `viewer` | `VIEWER` | 纯只读 |

这四组账号只用于本地开发。

## 接口一览

前缀统一是 `/api/v1`。下面是实际挂上去的路由，可以用 `app.openapi()["paths"]` 直接核对。

### 健康检查

```text
GET  /health                服务存活
GET  /health/database       数据库连通性
```

### 认证

```text
POST /auth/login            登录，返回 access token
GET  /auth/me               当前用户信息（含角色和权限点）
```

### 资产

```text
GET  /assets                列表（游标分页）
GET  /assets/{asset_id}     详情
```

### 工单

```text
GET  /work-orders                         列表
POST /work-orders                         创建
GET  /work-orders/{work_order_id}         详情
POST /work-orders/{id}/assign             分派
POST /work-orders/{id}/start              开始处理
POST /work-orders/{id}/complete           完成
POST /work-orders/{id}/close              关闭
POST /work-orders/{id}/reject             驳回
POST /work-orders/{id}/records            追加处理记录
```

五个流转动作各占一个独立路径，而不是一个 `PATCH /status` 带个参数。好处是权限点能直接挂在路径上（分派是 `work_order:assign`，跟状态更新分开），而且 Swagger 里每个动作是一条清清楚楚的记录。

### 工时与物料

```text
GET  /labor                 工时列表
POST /labor                 录入一条工时
GET  /transactions          交易列表
GET  /transactions/{id}     交易详情，含逐行明细
```

### 聚合

```text
GET  /dashboard/overview    首页指标 + 图表，走 5 分钟 TTL 缓存
```

### 系统管理

```text
GET  /system/users                    用户列表
GET  /system/roles                    角色列表（含各自的权限点）
PUT  /system/users/{user_id}/roles    改某个用户的角色
```

### 分页

列表接口用游标分页，不用 `page` / `page_size`：

```text
请求：GET /work-orders?limit=20&after_id=1234567

响应：{
  "code": 0,
  "message": "success",
  "data": {
    "items": [ ... ],
    "meta": { "limit": 20, "next_cursor": 1234587, "has_more": true }
  }
}
```

第一页不传 `after_id`，之后把上一页的 `next_cursor` 原样传回 `after_id` 就行。响应里没有 `total`：实测 `work_orders` 上算一次 `COUNT(*)` 要 322\~358 ms，而游标取 21 行只要 1.2\~1.6 ms，差了 200 多倍。游标分页本来就跳不了页，报一个用户用不上的总数、还搭上 300 毫秒，不划算。

`/system/users` 是唯一还用 `page` / `page_size` 的 —— 用户表只有几行，怎么翻都无所谓。

四个大列表（资产、工单、工时、交易）目前只有翻页，没有过滤和排序参数；规格里列过的那些还没接上去，哪些做了哪些没做在 `docs/api.md` 里逐条记着。

### 返回结构

成功和失败长得一样，看 `code` 就知道成没成：`code == 0` 是成功，数据在 `data` 里。

```json
{ "code": 0, "message": "success", "data": {} }
{ "code": 40900, "message": "Cannot COMPLETE a work order in status PENDING.", "data": null }
```

错误码是五位数字，前三位跟着 HTTP 状态码走（`40400` 对 404，`40900` 对 409，`50001` 对数据库错误），后两位区分同一状态码下的不同情形。比如同为 409，`40900` 是「这个动作在当前状态下不允许」，`40901` 是「两个人同时改同一行，你慢了一步」——前者该刷新看看到哪一步了，后者重试一下可能就成了，前端能分别处理。

## 测试

```powershell
cd backend
uv run pytest -v
```

23 个测试，全是纯单元测试，不碰数据库 —— 谁 clone 下来都能直接跑。

| 文件 | 覆盖什么 |
| --- | --- |
| `test_work_order_status.py` | 状态机：6 个状态 × 5 个动作的全部 30 种组合 |
| `test_security.py` | 密码哈希（加盐）、JWT 验签（篡改 / 过期 / 错密钥 / alg=none 绕过） |
| `test_cache.py` | TTL 缓存：惰性删除、命中不重算、十个线程同时未命中只算两次 |
| `test_work_order_sla.py` | SLA 计算：四个优先级的目标时长、跨天 |

期望值都是照着业务规则写的，不是从实现里反推的 —— 反推的话实现写错、期望值跟着错，测试照样全绿，等于没测。

接口层的验证是另一套：真实起服务、打 HTTP、拿聚合结果跟直接查库的数字对账。那批脚本依赖这份 861 万行的数据，所以没进仓库。

## 性能设计

八百万行的表上，随便一个聚合都可能变成全表扫描，所以几个关键查询都是先量再定。

### 趋势窗口卡在 12 个月

工单趋势、工时趋势、交易趋势和平均处理周期都只看最近 12 个月。这是量出来的边界，不是拍脑袋：

| 时间窗 | 平均处理周期 | 耗时 | 执行计划 |
| --- | ---: | ---: | --- |
| 全历史 | 50.72 天 | 3125 ms | `type=ALL` |
| 最近 12 个月 | 22.04 天 | 147 ms | `type=range`，走 `ix_work_orders_request_date` |
| 最近 24 个月 | 24.80 天 | 2935 ms | `type=ALL`，又掉回全表扫 |

24 个月的单数只比 12 个月多 1.3 倍，耗时却是 20 倍。原因不在数据量，在于窗口一大，优化器就不认为走日期索引划算了，直接改成顺序扫描。所以 12 往上加一格是塌方而不是缓降。

### 高维护资产拆两步

「维修次数最多的十项资产」如果写成一张 JOIN（按 `asset_id` 分组、同时取资产名），实测 5852 ms，执行计划里 `assets` 那边是 `type=ALL`、`rows=151339`。拆成两步只要 367 ms：

1. 先按 `asset_id` 分组取 top 10，走 `ix_work_orders_asset_id`，`Using index`
2. 再拿这 10 个 id 按主键捞名字，0.4 ms

省了 15.9 倍。问题不在 JOIN 本身，而在这个 JOIN 让优化器挑了个坏计划——拆开等于替它把选择做了。

### 知道哪里还没做好

工时趋势图带上 `SUM(hours)` 和 `SUM(cost)` 之后，`work_date` 上的索引就完全用不上了：只 `COUNT(*)` 是 94 ms 走 `type=range`，加上两个 `SUM` 之后变成 3083.7 ms、`type=ALL`、`rows=3159256`，而且限 12 个月和限 24 个月几乎没有差别——说明它压根没在按时间窗筛。根因是这两列不在索引里，走索引要回表 39 万次，优化器一算不如顺序扫。它是九个图表里最贵的一格，根治办法是建一个 `(work_date, hours, cost)` 的覆盖索引，目前没做。

### 缓存

`/dashboard/overview` 是唯一走缓存的读接口。它一次要跑 15 条 SQL 做聚合，冷态十几秒到二十秒（两次实测分别 13.8 秒和 19.6 秒，差在 MySQL 的 buffer pool 热不热，这类数字不该只报一次）；缓存命中之后只剩 HTTP 往返的十几毫秒，SQL 一条都不发。

缓存是进程内的（5 分钟 TTL），不是 Redis。理由是这个 key 只有个位数，进程内一张字典就够，为它引入一整个 Redis 组件不划算。有两条配套规矩：

- 工单写操作之后清缓存，而且要先提交再清（反过来会清掉一个还没生效的旧状态）
- 缓存里放 Pydantic 对象不放 ORM 对象（ORM 对象脱离 session 会抛 `DetachedInstanceError`）

另外有个信号量把同时真跑的聚合压到 2 个，挡的是缓存刚好过期、十个请求一起涌进来的那一瞬间。

### 列表查询

- 工单列表的关键词搜索走 FULLTEXT 索引，不是 `LIKE '%关键词%'`——220 万行上的前后通配 `LIKE` 用不上索引
- 状态这类选择性很差的列，走索引反而比全表扫慢。实测查 `status='COMPLETED'`（占总数的 93.03%）走索引 1017.6 ms，全表扫 248.7 ms，慢四倍。所以这类查询交给优化器自己判断
- 一次条件聚合比多次 `COUNT` 分开查快：1143.4 ms 对 1304.3 ms

## 已知限制

- 本仓库只包含后端，前端不在这里
- 数据集不随仓库分发，跑起来需要自己准备那份 MySQL 数据
- Dashboard 首次聚合依赖大表扫描，冷态十几秒到二十秒，靠 5 分钟缓存兜住；缓存失效后的第一个请求还是得等
- 工时趋势带 `SUM` 的查询退化成全表扫（约 3 秒），缺一个覆盖索引
- 缓存是单进程的，多实例部署时需要换成共享缓存
- 测试只覆盖状态机，其余模块靠一次性验收脚本验证，那些脚本没有进仓库
- 没有 Dockerfile 和 CI 配置
