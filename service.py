"""
算法服务启动脚本（向后兼容入口）
================================
仅保留 `python service.py` 的启动方式；服务实现见 server 包。

推荐统一使用全局启动脚本：
    python main.py              # 无参数默认启动算法服务
    python main.py serve [--host H] [--port P]

监听 IP/端口通过环境变量 SERVER_HOST / SERVER_PORT 配置（config.py）：
    SERVER_HOST=10.x.x.x SERVER_PORT=8080 python service.py
"""
from __future__ import annotations

from common.logging_utils import setup_logging
from server import run_server

if __name__ == '__main__':
    setup_logging()
    run_server()
