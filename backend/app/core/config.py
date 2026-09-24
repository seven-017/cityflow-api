from functools import lru_cache  #装饰器，把函数运行的结果缓存起来
from pathlib import Path  #用于处理文件路径

from pydantic_settings import BaseSettings, SettingsConfigDict #Pydantic 的配置管理库，Pydantic 会校验类型，写错类型会报错

BACKEND_ROOT = Path(__file__).resolve().parents[2] #把文件路径转换为绝对路径，再上两级，回到/backend/


class Settings(BaseSettings):
    # 控制日志啰不啰嗦：true 打 DEBUG，false 只到 INFO
    app_debug: bool = False

    database_url: str = (
        "mysql+pymysql://cityflow:cityflow@127.0.0.1:3306/cityflow?charset=utf8mb4"
    )

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore", #忽略额外的环境变量
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
