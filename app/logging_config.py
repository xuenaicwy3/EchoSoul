"""
日志系统配置
使用 Python 标准 logging 模块，输出格式包含时间、模块名、级别和消息
"""
import logging
import sys
from app.config import Settings

def setup_logging(settings: Settings) -> None:
    """根据配置初始化根日志器"""
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    # 格式：[时间] 模块名                 级别    消息
    formatter = logging.Formatter(
        '[%(asctime)s] %(name)-25s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    # 移除已有的处理器，避免重复输出
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)

    logging.info("日志系统初始化完成，级别=%s", settings.LOG_LEVEL)