"""
server — 算法服务包（HTTP）
============================
- create_app()  : 应用工厂，只负责组装 Flask 应用并注册全部算法蓝图
- run_server()  : 服务启动入口（监听地址来自 config.ServiceConfig）

本包只做**接口暴露 + 调用算法**，不包含业务逻辑；
算法模块在 modules/ 注册中心声明（见 modules/__init__.py），
blueprints/__init__.py 的通用工厂自动为其生成并注册蓝图。
"""
from __future__ import annotations

import logging

from flask import Flask

from .blueprints import register_blueprints

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """Flask 应用工厂。static_folder=None：不暴露默认静态路由，
    整个服务只暴露各蓝图声明的接口路由。
    """
    app = Flask(__name__, static_folder=None)
    register_blueprints(app)
    return app


def run_server(host: str = None, port: int = None, debug: bool = None) -> None:
    """启动算法服务。缺省参数取 config.ServiceConfig（环境变量 SERVER_HOST/SERVER_PORT）。

    算法串行同步运行、使用模块级全局状态，不支持并发/异步：
    必须以**单进程单线程**方式启动（threaded=False），请求按到达顺序串行处理，
    切勿用多线程/多进程 WSGI 部署。
    """
    from config import ServiceConfig

    cfg = ServiceConfig()
    app = create_app()
    h = host or cfg.host
    p = port or cfg.port
    d = cfg.debug if debug is None else debug

    logger.info("算法服务启动（单线程串行处理请求）: http://%s:%s", h, p)
    app.run(host=h, port=p, debug=d, threaded=False)
