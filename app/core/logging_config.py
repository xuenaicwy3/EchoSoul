"""
日志系统配置。

使用 Python 标准 logging 模块，输出格式包含时间、模块名、级别和消息。
"""
import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """初始化根日志器。

    Args:
        level: 日志级别字符串，如 "DEBUG"、"INFO"、"WARNING"、"ERROR"
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter(
        "[%(asctime)s] %(name)-25s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)

    logging.info("日志系统初始化完成，级别=%s", level)
