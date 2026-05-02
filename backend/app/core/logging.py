"""日志配置模块

提供统一的日志格式和配置，支持 text（开发）和 json（生产）两种格式。
"""

import logging
import sys


class JsonFormatter(logging.Formatter):
    """JSON 格式化器，便于日志采集系统解析"""

    def format(self, record: logging.LogRecord) -> str:
        import json

        log_data = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False)


def setup_logging(level: str = "INFO", fmt: str = "text") -> None:
    """初始化全局日志配置

    Args:
        level: 日志级别（DEBUG / INFO / WARNING / ERROR）
        fmt: 输出格式（text / json）
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)

    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))

    root.addHandler(handler)

    # 抑制第三方库的 DEBUG 日志，只对我们自己的模块开启 DEBUG
    noisy_loggers = [
        "httpcore", "httpx", "openai", "urllib3", "sse_starlette",
        "langchain", "langchain_openai", "langchain_core", "pymilvus",
        "aiomysql", "passlib",
    ]
    for name in noisy_loggers:
        logging.getLogger(name).setLevel(logging.INFO)
    # SQLAlchemy 只显示 WARNING，不显示每条 SQL
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.orm").setLevel(logging.WARNING)
