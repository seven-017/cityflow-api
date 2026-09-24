import logging
from logging.config import dictConfig

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    # app_debug 开了就用 DEBUG，没开就只到 INFO
    level = logging.DEBUG if settings.app_debug else logging.INFO

    dictConfig(
        {
            "version": 1,
            # 不加这行的话，dictConfig 会把已经存在的 logger 全禁用掉，
            # uvicorn 启动时早就建好了自己的 logger，结果就是服务器日志全没了
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    # 时间 级别 哪个模块 消息，时间用 ISO 8601，好排序也好被机器解析
                    "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
                }
            },
            "handlers": {
                # 目前就打到控制台，以后要落文件再往这儿加一个
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "level": level,
                }
            },
            "root": {
                "handlers": ["console"],
                "level": level,
            },
            "loggers": {
                # uvicorn 的访问日志单独配，propagate 关掉，
                # 不然它会同时往 root 冒泡，屏幕上每条请求打两遍
                "uvicorn.access": {
                    "handlers": ["console"],
                    "level": level,
                    "propagate": False,
                }
            },
        }
    )
