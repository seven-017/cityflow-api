# 接口说明

这份是动手写之前定的接口规格。写的过程中有几处参数没做、几处路径改了，都在每个接口下面用「本仓库」标出来。

真正的接口清单以 `app.openapi()["paths"]` 为准 —— 那份是代码自己生成的，不会过期。这份记的是「当初要求什么、后来怎么做的」。

## 基本约定

- 前缀 `/api/v1`
- 数据格式 JSON
- 认证 `Authorization: Bearer <token>`
- Swagger 在 `/docs`，OpenAPI 在 `/api/v1/openapi.json`

成功和失败的返回体长得一样，看 `code` 就知道成没成：

```json
{ "code": 0, "message": "success", "data": {} }
{ "code": 40300, "message": "Permission denied.", "data": null }
```

## 分页

规格写的是 `page` / `page_size`，`page_size` 最大 100，响应里给 `page` / `page_size` / `total` / `pages`。

本仓库的四个大列表改成了游标：

```text
请求：GET /work-orders?limit=20&after_id=1234567

响应：{
  "items": [],
  "meta": { "limit": 20, "next_cursor": 1234587, "has_more": true }
}
```

第一页不传 `after_id`，之后把上一页的 `next_cursor` 原样传回来。没有 `total`，也没有 `page` / `pages`。改的理由和实测数字在 `architecture.md`。

`/system/users` 还是 `page` / `page_size`，没跟着改。

## 认证

### `POST /auth/login`

```json
{ "username": "admin", "password": "CityFlow@123" }
```

`data` 里返回 `access_token`、`token_type`、`expires_in`、`user`。用户名密码走请求体不走 URL（URL 会进访问日志）。

登录成功和失败都写操作日志。

### `GET /auth/me`

返回当前用户、角色和权限点。前端刷新页面靠它恢复登录状态。

## 资产

### `GET /assets`

规格参数：`keyword` / `asset_type` / `status` / `category` / `sort_by` / `sort_order` / `page` / `page_size`

本仓库：只有 `after_id` 和 `limit`。八个过滤和排序参数都没做。

### `GET /assets/options`

规格要求返回资产类型、状态和分类的选项列表。

本仓库：没做。

### `GET /assets/{asset_id}`

规格返回：资产基础信息 + 工单 / 工时 / 交易的统计 + 最近工单。

本仓库：只返回资产本身的 17 个字段，三块统计和最近工单都没做。查不到返 404，不返回 `data: null`。

## 工单

### `GET /work-orders`

规格参数：`keyword` / `status` / `work_type` / `data_source` / `priority` / `asset_id` / `assigned_to_id` / `request_date_from` / `request_date_to` / `sort_by` / `sort_order` / `page` / `page_size`

本仓库：只有 `after_id` 和 `limit`。十三个参数里做了零个过滤。

`keyword` 那一条本来是有的：工单表上建了 FULLTEXT 索引（`description` + `assigned_title`），222 万行上用前后通配的 `LIKE` 等于全表扫，所以索引是先建的。接口这一层暂时没接上去。

### `GET /work-orders/options`

规格要求返回状态、工单类型、来源、优先级和可分配工程师。

本仓库：没做。

### `POST /work-orders`

规格的请求体：

```json
{
  "asset_id": 123,
  "description": "Repair playground gate",
  "work_type": "Repair",
  "priority": "P2",
  "scheduled_end_date": "2026-09-25"
}
```

返 201。建的工单带自己的编号（`PF-` 加 12 位十六进制）和数据源 `SYNTHETIC_PLATFORM`，`priority` 限定 `P1`\~`P4`，建单那一刻按优先级算出 `sla_deadline`。

### `GET /work-orders/{id}`

规格返回七块：工单信息、资产与分派人、状态时间线、处理记录、工时汇总、交易汇总、操作日志。

本仓库：做了四块 —— 工单本身的字段、`asset_id`、`assigned_to_id`、状态流水、处理记录。工时汇总、交易汇总、操作日志没做；资产和分派人只给了 id，没有 JOIN 出名字。

状态流水和处理记录不分页，因为这两张子表的行数天生就小（一单最多几条流水、几十条备注）。

### `PATCH /work-orders/{id}/assign`

规格是一个 `PATCH`，请求体带 `assignee_id` 和 `reason`。

本仓库：路径是 `POST /work-orders/{id}/assign`，请求体只带 `assignee_id`。

改成独立路径的理由是权限点能直接挂在路径上（分派是 `work_order:assign`，跟状态更新分开），而且 Swagger 里每个动作是一条独立的记录。

### `PATCH /work-orders/{id}/status`

规格是一个 `PATCH`，请求体带 `to_status` 和 `reason`，也就是「改状态」这个动作由调用方指定目标状态。

本仓库：拆成了四个独立的 `POST`，目标和动作名绑死：

```text
POST /work-orders/{id}/start       -> IN_PROGRESS
POST /work-orders/{id}/complete    -> COMPLETED
POST /work-orders/{id}/close       -> CLOSED
POST /work-orders/{id}/reject      -> REJECTED     带 reason
```

这么拆的原因：让调用方指定 `to_status` 的话，合法组合的校验就得在运行时做，而且「想驳回一个已完成的单」这种错只能靠比对字符串发现。动作名跟目标状态绑死之后，非法流转在状态机那张表上就挡住了，返 409。

四个动作里只有 `reject` 要请求体（要填原因），另外三个不需要 —— 谁点的、什么时候点的，服务端自己知道。

### `POST /work-orders/{id}/records`

```json
{ "content": "Inspection completed." }
```

返 201。这是往工单底下新建一个子资源，所以状态码跟建工单对齐。

权限跟流转共用 `work_order:update`，但不吃「只能操作自己的单」那条限制 —— 那条管的是「谁能推动这张单」（状态流转），写备注不推状态。

## 工时

### `GET /labor`

规格参数：`keyword` / `trade` / `operation_type` / `work_order_id` / `asset_id` / `date_from` / `date_to` / `sort_by` / `sort_order` / `page` / `page_size`

本仓库：只有 `after_id` / `limit` / `work_order_id`。

没做的八个分三类：

- `keyword`、`date_from` / `date_to`：没有索引撑着，320 万行上做 `LIKE '%xx%'` 或者日期范围全扫，快不了
- `asset_id`：表上根本没这一列。`work_order_labor` 的字段是从 AMPS 原始数据映射过来的，那些字段里就没有资产。要按资产过滤只能 JOIN 工单表（222 万行），而且资产那边要的是统计不是明细，那是聚合接口的事
- `trade`、`operation_type`、`sort_by`、`sort_order`：见下面「还悬着的问题」

### `GET /labor/options`

规格要求返回工种和作业类型。

本仓库：没做。

### `POST /labor`

录一条工时。`source_record_id`、`data_source`、`entered_at` 三个字段由服务端填 —— 编号得保证不重复，数据源必须是 `SYNTHETIC_PLATFORM`（写成 `REAL_PUBLIC` 这条记录就永远没人能改了），录入时刻只有一个正确答案。

返 201。落库两样东西：工时本身 + 一条操作日志。

## 交易

### `GET /transactions`

规格参数：`keyword` / `transaction_type` / `status` / `work_order_id` / `asset_id` / `date_from` / `date_to` / `sort_by` / `sort_order` / `page` / `page_size`，共 10 个。

本仓库：只有 `after_id` / `limit` / `work_order_id`。

### `GET /transactions/options`

规格要求返回交易类型和状态。

本仓库：没做。

### `GET /transactions/{transaction_id}`

规格返回「交易头信息和逐行物料明细」。

本仓库：做了，但明细单独分页（`detail_after_id` / `detail_limit`）。规格那句读起来像要一次全给，那样不行：多数单只有一行，但尾部有单子能到几千行。参数名带 `detail_` 前缀是因为这个接口有两个东西 —— 被路径定死的交易单（只有一张，不用分页）和它的明细（可能几千行，要分页），光一个 `after_id` 说不清在翻什么。

## Dashboard

### `GET /dashboard/overview`

规格返回：指标汇总、工单趋势、状态分布、工单类型、资产类型、高维护资产、平均处理周期、工时趋势、交易趋势、最近工单。

本仓库：九项图表全做了，指标汇总那十个字段是另外挑的 —— 规格里那一行只写了「指标汇总」四个字，一个字段名都没给。

没有查询参数，也不是漏了：规格里带条件（日期范围、资产类型、工单类型）的是隔壁 `/analytics/overview`。

走 5 分钟进程内缓存。

### `GET /analytics/overview`

规格参数：`date_from` / `date_to` / `asset_type` / `work_type`。

本仓库：没做。

## 系统管理

```text
GET   /system/users                 分页用 page / page_size
GET   /system/roles                 角色 + 各自的权限点
PUT   /system/users/{id}/roles      改角色
```

需要 `user:manage` 或 `role:manage`。

规格里写的是 `PATCH /system/users/{id}/roles`，本仓库用的是 `PUT` —— 这个接口是「把角色设成这几个」，整份替换，用 `PUT` 更贴语义。

规格里还有两个没做：

- `PATCH /system/users/{id}/status`（停用/启用用户）
- `GET /operation-logs`（查操作日志）

操作日志本身一直在写，「查日志」那个接口没做，所以 `operation_log:read` 这个权限点目前悬着。

## 健康检查

```text
GET /health              服务存活
GET /health/database     数据库连通性
```

## 错误码

五位数字，前三位跟着 HTTP 状态码走，后两位区分同一状态码下的不同情形。

| HTTP | code | 含义 |
| ---: | ---: | --- |
| 401 | `40100` | 未登录、token 无效或过期 |
| 403 | `40300` | 权限不足 |
| 404 | `40400` | 资源不存在 |
| 409 | `40900` | 这个动作在当前状态下不允许 |
| 409 | `40901` | 资源被别处改过了，重新拉一次再试 |
| 422 | `42200` | 请求参数校验失败 |
| 500 | `50000` | 未处理异常 |
| 500 | `50001` | 数据库异常 |

`40900` 和 `40901` 分开是有用的：前者该刷新看看到哪一步了，后者重试一下可能就成了。混成一个码的话前端只能一律让用户刷新，白丢一次本来能成功的操作。

参数校验失败返 422 时会带上具体错在哪一项（在 `data` 里），方便前端定位。

## 规格里有、本仓库没做的

汇总一份，免得一条条翻：

| 接口 | 状态 |
| --- | --- |
| `GET /analytics/overview` | 没做 |
| `GET /assets/options` | 没做 |
| `GET /work-orders/options` | 没做 |
| `GET /labor/options` | 没做 |
| `GET /transactions/options` | 没做 |
| `GET /operation-logs` | 没做 |
| `PATCH /system/users/{id}/status` | 没做 |

还有一批「接口做了但参数没做全」的：四个大列表的过滤和排序参数、资产详情的三块统计、工单详情的工时/交易/日志三块。这些都在上面各节里写了。
