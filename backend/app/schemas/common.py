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
