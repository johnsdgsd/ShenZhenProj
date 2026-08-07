"""
全局启动脚本 — HTTP 算法服务
============================
用法：
    python main.py                               # 直接启动算法服务（默认 0.0.0.0:5000）
    python main.py serve [--host H] [--port P] [--debug]   # 显式子命令（等价）

生产环境部署：
    SERVER_HOST=10.x.x.x SERVER_PORT=8080 python main.py serve

监听地址优先级：命令行 --host/--port > 环境变量 SERVER_HOST/SERVER_PORT > 默认 0.0.0.0:5000。

离线 Excel 兑底请使用独立脚本 cli.py：
    python cli.py <输入Excel路径> [-o 输出Excel路径]
"""
from __future__ import annotations

import argparse
import logging
import sys

logger = logging.getLogger(__name__)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # 兼容旧写法：python main.py serve [options]
    if argv and argv[0] in ('serve', 'server', '--serve'):
        argv = argv[1:]
    return _cmd_serve(argv)


def _cmd_serve(argv) -> int:
    parser = argparse.ArgumentParser(prog='main', description='启动检定排程算法服务')
    parser.add_argument('--host', help='监听地址（默认取环境变量 SERVER_HOST，再默认 0.0.0.0）')
    parser.add_argument('--port', type=int, help='监听端口（默认取环境变量 SERVER_PORT，再默认 5000）')
    parser.add_argument('--debug', action='store_true', help='开启 Flask 调试模式')
    args = parser.parse_args(argv)

    setup_logging()
    try:
        from server import run_server
        run_server(host=args.host, port=args.port, debug=args.debug)
    except Exception:
        logger.exception("算法服务启动失败")
        return 1
    return 0


def setup_logging():
    """配置根 logger（幂等，供 main 与 server 共用）。"""
    from common.logging_utils import setup_logging as _setup
    _setup()


if __name__ == '__main__':
    sys.exit(main())
