# 架构设计

## 分层

```text
HTTP 请求
  -> Router        路径、方法、状态码，参数校验，取当前用户
    -> Service     业务规则：状态机、权限、SLA、缓存编排、写操作日志
      -> Repository  拼 SQL，分页排序筛选，聚合，ORM 持久化
        -> Model    SQLAlchemy 表定义
          -> MySQL 8
```

### Router

定义 HTTP 路径、方法和状态码，用 Pydantic 校验请求参数，取当前用户，调 Service。不直接执行 SQL，也不实现工单状态机。

权限点通过依赖注入挂在路由上，形如 `Depends(require_permissions(PermissionCode.X))`。校验发生在进业务逻辑之前，业务代码里不用再写一遍。

### Service

认证与 JWT 签发、RBAC 组合、工单创建分派流转、SLA 计算、统计组织、操作日志写入。

工单的状态流转集中在一个地方，不让不同接口各自判一遍。

### Repository

查询构造、分页排序筛选、聚合统计、ORM 持久化。不处理 HTTP 错误，也不决定业务权限 —— 那两件事归上层。

方法返回 `NamedTuple` 而不是 ORM 对象。查出来的常常是聚合值或者跨表的几列，硬塞进某个 ORM 类里不合适，而且不用担心 session 关闭之后属性读不了。

### Model 与 Schema

`models/` 描述数据库映射和表关系，`schemas/` 描述接口的输入输出。两者分开，接口不直接依赖 ORM 对象。

代价是查出来之后要手动把字段一个个搬进 schema。好处是表加列时搬运函数纹丝不动，坏处是漏搬了不报错、前端就是少个字段，得自己留意。

### 本仓库加的两条硬规矩

1. 只有 `repositories/` 里能出现 `select()`。Service 要数据就调 repository 方法。查询散在 service 里之后，想给某个查询调索引、想统计谁在扫大表，都找不到地方下手
2. `services/` 之间不许互相 import。两边都要用的抽到 `core/`（纯逻辑）或 `repositories/sql_helpers.py`（SQL 片段）

第二条有实例：双数据源那两个常量原本写死在工单 service 里，后来工时的写接口也要用同一对值，而工时不该反过来 import 工单模块，于是挪进了 `core/data_sources.py`。一旦 service 互引，调用链会变成网状，改一个函数的返回值要顺着两边都看一遍。

## 数据域

### `REAL_PUBLIC`

官方 AMPS 导入的五张表：资产、工单、工时、交易、交易明细。历史只读，用于查询、统计和关联，不修改原始记录。

### `SYNTHETIC_PLATFORM`

平台用户创建的：工单、状态历史、处理记录、用户、角色、权限、操作日志。

平台工单可以关联真实资产，但工单本身仍然明确属于平台数据。

## 认证与授权

```text
登录
  -> Argon2 校验密码
  -> 签发 JWT

请求
  -> Bearer token
  -> JWT 解码
  -> 查用户角色
  -> 汇总权限
  -> require_permissions 判断
  -> 进 Service
```

授权真正发生在后端。前端路由守卫只负责体验，不构成授权。

## 工单状态机

```text
PENDING -> ASSIGNED -> IN_PROGRESS -> COMPLETED -> CLOSED
PENDING -> REJECTED
ASSIGNED -> REJECTED
```

两条关于角色的规则：

- Engineer 只能更新分配给自己的工单
- Engineer 只能执行 `ASSIGNED -> IN_PROGRESS` 和 `IN_PROGRESS -> COMPLETED`；Admin 和 Dispatcher 可以执行管理型转换

这两句看着像同一条，其实是两件事，分别是「哪张单」和「哪个动作」，都得判。

完整的转移表和补充规则见 `business-rules.md`。

## 查询与性能

### 分页

规格写的是 `page` / `page_size`，`page_size` 最大 100，列表和计数分离。

本仓库的四个大列表（资产、工单、工时、交易）改成了游标分页 —— 用的是 `after_id` / `limit`，响应里给 `next_cursor` 和 `has_more`，没有 `total`。理由是实测出来的：

| 表 | 行数 | `OFFSET` 翻页一次 | 游标取 21 行 |
| --- | ---: | ---: | ---: |
| `assets` | 14.8 万 | 16~23 ms | 同量级 |
| `transactions` | 75 万 | 0.92 s | — |
| `work_orders` | 222 万 | — | 1.2~1.6 ms |
| `work_order_labor` | 320 万 | 3.5 s | — |

`total` 也一并去掉了：算一次 `COUNT(*)` 要 322~358 ms，而游标取 21 行只要 1.2~1.6 ms，差 200 多倍。游标分页本来就跳不了页，报一个用户用不上的总数还搭上 300 毫秒，不划算。

`/system/users` 还是老式的 `page` / `page_size`，没跟着改 —— 用户表只有几行，`COUNT(*)` 和 `OFFSET` 都无所谓。

排序稳定性：列表按主键排，不用可能重复的字段。分页时排序字段一旦有重复值，第 1 页和第 2 页可能出现同一条记录，也漏掉另一条。

### 避免 N+1

规格说工单列表一次 JOIN 出资产和分派人。本仓库没这么干，因为量出来反了：

```text
select(WorkOrder) WHERE id > ? ORDER BY id LIMIT 21
  带 JOIN（created_by / assigned_to）
    16614 ms   work_orders type=range rows=1079352
               Extra: Using temporary; Using filesort
               users_1 type=ALL  Using join buffer (hash join)
  去掉 JOIN
    2.5 ms
```

那条 LEFT JOIN 让优化器挑了 hash join，于是拿不到主键顺序，只能把 107 万行先查出来排一遍再 limit —— `LIMIT 21` 本来能省的全白省了。

而且这个 JOIN 在这张表上永远是白搭：`created_by_id` 和 `assigned_to_id` 实测 222 万行 100% 是 NULL（那是平台自己录单时才会填的列，库里现在全是官方导进来的老数据）。所以改成默认的按需加载：真有人要读那张单的分派人，那一刻多查一条就是。

「避免 N+1」是个正确的目标，但达成它的手段不止 JOIN 一种。加 JOIN 之前先看执行计划，别照着原则抄。

### 搜索

- 编号类走前缀索引
- 描述和标题走 MySQL FULLTEXT（`ix_work_orders_search`）。222 万行上的前后通配 `LIKE '%关键词%'` 用不上索引，等于全表扫

### Dashboard 缓存

Dashboard 聚合较重。当前用：

- 进程内 TTL 缓存，5 分钟
- 最多 2 个并发聚合任务，降低本地 MySQL I/O 争用
- 工单写操作清除缓存

没有引入 Redis。多实例部署时应替换为共享缓存。

缓存里放的是 Pydantic 对象不是 ORM 对象 —— ORM 对象脱离 session 之后读属性会抛 `DetachedInstanceError`。

清缓存的顺序是先提交再清。反过来会清掉一个还没生效的旧状态：事务还没提交，别的请求来算了一遍、把旧数据又写回缓存，然后这次提交完再清一次也救不回来。

那个「最多 2 个并发」挡的是「缓存刚过期、十个请求一起涌进来」的那一瞬间 —— 十个都去查库会把 MySQL 的 I/O 抢干净。它是「多个请求之间」的限制，不是「一次聚合能开几个线程」。

## 并发

工单的状态流转是「先查、再判、最后改」。判完到写库之间那段空隙原来是敞着的，两个请求前后脚进来会双双通过：

```text
T1 点开始：读到 ASSIGNED -> 判定合法 -> 写入 IN_PROGRESS
T2 点驳回：读到 ASSIGNED -> 判定合法 -> 写入 REJECTED
最终状态：REJECTED
流水 4 行：两条从 ASSIGNED 出发、方向相反的流转
```

麻烦的是流水里两条相反的记录都留着，而工单只有一个最终状态，事后翻流水说不清它是被开工了还是被驳回了。更烦的是 T1 拿到的是 200 加一个 IN_PROGRESS，界面上写着「已开工」，库里其实是 REJECTED。

根子不是缺锁 —— 行锁挡的是「同时写」，挡不住「基于一个已经过期的状态做判断」：后到的人照样能拿到锁、照样能写，他只是不该写。

修法是带条件的 UPDATE：`WHERE id = ? AND status = ?`，看返回的受影响行数。0 就说明有人先动手了，抛 409 让对方重试。流水和日志都还没写，直接回滚，不留半截数据。

`40900` 和 `40901` 是分开的两个码：前者是「这个动作在当前状态下就不允许」，后者是「判断没错，只是慢了一步」。不分开的话前端拿到 409 只能一律让用户刷新，白丢一次本来能成功的操作。

## 为什么不做更复杂的架构

微服务、消息队列、Kubernetes、DDD、GraphQL、分布式事务 —— 这些都不能弥补核心业务逻辑或者数据质量的问题，只会增加解释成本。当前保持单体可运行。
