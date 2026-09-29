from pydantic import BaseModel


class ApiResponse[T](BaseModel):
    """所有接口统一的返回壳子：code=0 就是成功，数据全在 data 里。

    这么包一层的好处：前端拿到的结构永远一样，
    判断成功与否只看 code，不用去猜每个接口长得像不像。

    写法说明：这里的 [T] 是 Python 3.12 之后的新语法（PEP 695），
    等价于老写法里的 Generic 基类，但少写一坨，也更好读。
    """

    code: int = 0
    message: str = "success"
    data: T


class PageMeta(BaseModel):
    """分页的"说明书"：这是第几页、一页多少条、总共多少条、总共多少页。

    为什么要 pages 而不让前端自己算：总条数会变，前端算出来的和数据库当下的
    可能不一样，由后端一次算好最省事。
    """

    page: int
    page_size: int
    total: int
    pages: int


class PageResponse[T](BaseModel):
    items: list[T]
    meta: PageMeta


class CursorMeta(BaseModel):
    """游标分页的说明书。

    跟 PageMeta 比，少了 page / pages —— 游标分页本来就跳不了页，
    还报个"第几页"是骗人的。多了两个：next_cursor（下一页从哪开始）、has_more（还有没有）。

    这里原本还有个 total，2026-09-29 删掉了。删它的三条理由，按重要性排：

    1. 它是 OFFSET 分页留下来的尾巴。第 15 步把分页从 page/page_size 改成游标时，
       同一批的 page / pages 都删了，total 漏了没删。它现在没有任何东西依赖它。

    2. 游标分页跳不了页，所以"共 2220853 条"这个数字对用户没有用处 ——
       他既不能跳到第 500 页，也不能拿它做什么判断。纯粹是个装饰。

    3. 它有实实在在的代价。实测（2026-09-29）：

           work_orders 上的 COUNT(*)      322~358 ms
           同一条列表查询（游标取 21 行）   1.2~1.6 ms

       差了 200 多倍。整个列表请求 437 ms 里，这个数字占了 330 ms，也就是 75%。
       换句话说：接口慢，慢的就是它一个字段。

    那"上 Redis 缓存一下"行不行？当时的四个方案（不报 / 只第一页算 / 上缓存 /
    用 information_schema 的估算值）代价都量过，最后还是选了不报。原因是：
    缓存该用在"确实需要、而且算起来贵"的地方，这儿两条都不满足 ——
    它不需要（第 2 条），它也不值得为它引入一整个 Redis 组件。
    真要看总量是 Dashboard 的事，那边一个页面可以缓存一次给好几个卡片复用。

    所以将来如果又想加回 total，先回答三个问题：
    谁在看这个数字？他是拿它做什么决定？这个决定值不值 330 毫秒？
    """

    limit: int
    # 下一页的起点：把这个数当下一次请求的 after_id 传回来就行。到底了就是 None
    next_cursor: int | None
    has_more: bool


class CursorResponse[T](BaseModel):
    items: list[T]
    meta: CursorMeta
