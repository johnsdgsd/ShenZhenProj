"""
环境配置模块
============
本模块**只做环境配置**（运行时环境参数），供其他模块导入。

- 业务常量（接口枚举字典 / Excel sheet 映射）→ `data/constants.py`
- 算法默认参数（SchedulingConfig）           → `algorithm/constants.py`

部署 IP/端口由企业方提供，通过环境变量配置，例如：
    SERVER_HOST=10.x.x.x SERVER_PORT=8080 python main.py serve
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# 日志级别（可选覆盖，默认 INFO）
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')


@dataclass
class ServiceConfig:
    """HTTP 算法服务监听参数（算法服务作为被调用方）。

    host / port 直接读环境变量 SERVER_HOST / SERVER_PORT，带默认值，
    不做额外覆盖逻辑（参考 Proj 项目 backend/config/config.py 的写法）。
    """
    host: str = os.environ.get('SERVER_HOST', '0.0.0.0')
    port: int = int(os.environ.get('SERVER_PORT', 5000))
    # 是否开启 Flask 调试模式（仅开发用，生产勿开）
    debug: bool = os.environ.get('SERVER_DEBUG', '0') == '1'
