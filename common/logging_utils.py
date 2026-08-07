"""
日志统一配置
============
setup_logging() 幂等：仅在根 logger 尚未配置时初始化，
避免 CLI 与 HTTP 两条路径重复配置产生重复 handler。

日志级别可通过环境变量 LOG_LEVEL 覆盖（config.LOG_LEVEL）。
"""
import logging
import sys

from config import LOG_LEVEL


def setup_logging(level=None):
    """初始化根 logger。重复调用安全（不会重复添加 handler）。

    :param level: 日志级别（logging 级别常量或字符串），缺省取环境变量 LOG_LEVEL。
    """
    if level is None:
        level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    root = logging.getLogger()
    if root.handlers:
        # 已配置过，仅校正级别
        root.setLevel(level)
        return
    logging.basicConfig(
        level=level,
        format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
        stream=sys.stdout,
    )
