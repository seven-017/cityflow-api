from functools import lru_cache  #装饰器，把函数运行的结果缓存起来
from pathlib import Path  #用于处理文件路径
from typing import Literal  #限定某个字段只能是列出来的那几个值

from pydantic import Field  #要写"默认值由函数现算"这种字段时用它
from pydantic_settings import BaseSettings, SettingsConfigDict #Pydantic 的配置管理库，Pydantic 会校验类型，写错类型会报错

BACKEND_ROOT = Path(__file__).resolve().parents[2] #把文件路径转换为绝对路径，再上两级，回到/backend/


class Settings(BaseSettings):
    app_name: str = "CityFlow API"  #会显示在 /docs 的标题上
    app_version: str = "0.1.0"  #接口版本号，单独一个地方管，免得各处的对不上
    # 当前跑在什么环境。写成 Literal 是为了让填错的值当场报错，而不是跑到一半才发现
    app_env: Literal["development", "test", "production"] = "development"
    # 控制日志啰不啰嗦：true 打 DEBUG，false 只到 INFO
    app_debug: bool = False
    api_v1_prefix: str = "/api/v1"  #所有接口的公共前缀，将来出 v2 就再加一个前缀

    # 这里默认写 3306 是"通用情况"。我这台机器上 cityflow 在 3307，
    # 靠的是 .env 里那行 DATABASE_URL 覆盖掉它 —— 默认值放通例，实情放 .env
    database_url: str = (
        "mysql+pymysql://cityflow:cityflow@127.0.0.1:3306/cityflow?charset=utf8mb4"
    )
    # 前端跑起来后是 5173，后端 8000，不放进这个白名单浏览器会拦跨域请求。
    # default_factory 的意思是"每次实例化时现调一次这个函数"，不能直接写 []，
    # 写 [] 的话所有实例会共用同一个列表对象，改一个全跟着变
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )
    # 要不要把每条 SQL 原样打到日志里，只有查慢查询的时候才开
    sql_echo: bool = False
    # 允许用 LOAD DATA LOCAL INFILE 从本地文件批量灌数据，导那 861 万行就靠它
    mysql_local_infile: bool = True

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore", #忽略额外的环境变量
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
