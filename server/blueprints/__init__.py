"""
蓝图注册中心
============
每个算法模块对应一个独立蓝图模块（blueprints/<name>.py），
新增算法接口时：新建蓝图模块 + 在本文件 _BLUEPRINTS 列表追加，即自动注册。

约定：各蓝图内部用**完整接口路径**声明路由（如
/restful/busiInterface/ipsService/detectPlanScheduling），注册时不设 url_prefix。
"""
import logging

from .detect_plan_scheduling import bp as detect_plan_scheduling_bp

logger = logging.getLogger(__name__)

# 所有算法蓝图（按需在此追加新蓝图）
_BLUEPRINTS = [
    detect_plan_scheduling_bp,
]


def register_blueprints(app) -> None:
    """把全部算法蓝图注册到 Flask 应用。"""
    for bp in _BLUEPRINTS:
        app.register_blueprint(bp)
        logger.info("注册蓝图: %s", bp.name)
