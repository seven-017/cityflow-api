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
    """

    limit: int
    total: int
    # 下一页的起点：把这个数当下一次请求的 after_id 传回来就行。到底了就是 None
    next_cursor: int | None
    has_more: bool


class CursorResponse[T](BaseModel):
    items: list[T]
    meta: CursorMeta
