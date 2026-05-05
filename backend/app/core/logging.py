"""日志配置模块

提供统一的日志格式和配置，支持 text（开发）和 json（生产）两种格式。
"""

import logging
import logging.handlers
import sys
import io
import os
from pathlib import Path


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


class FlushFileHandler(logging.FileHandler):
    """每次写入后立即刷新的文件处理器"""

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def _get_log_dir() -> Path:
    """获取日志目录（项目根目录下的 logs/）"""
    # 从当前文件向上找项目根目录（通过 docker-compose.yml 或 .git 判断）
    current = Path(__file__).resolve().parent
    for _ in range(5):
        if (current / "docker-compose.yml").exists() or (current / ".git").exists():
            break
        current = current.parent
    log_dir = current / "logs"
    log_dir.mkdir(exist_ok=True)
    return log_dir


def setup_logging(level: str = "INFO", fmt: str = "text") -> None:
    """初始化全局日志配置

    Args:
        level: 日志级别（DEBUG / INFO / WARNING / ERROR）
        fmt: 输出格式（text / json）
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Windows 下强制 stdout 使用 UTF-8 编码
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    formatter: logging.Formatter
    if fmt == "json":
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    # 文件输出（每次写入后立即刷新）
    log_dir = _get_log_dir()
    log_file = log_dir / "backend.log"
    file_handler = FlushFileHandler(
        log_file, encoding="utf-8", mode="a", delay=False,
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

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
