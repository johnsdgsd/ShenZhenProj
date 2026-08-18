"""
蓝图注册中心（通用工厂）
========================
遍历 modules.all_modules()，为每个已接入 HTTP 的算法模块生成蓝图并注册。

通用流程（与模块实现无关）：
    请求体 JSON -> module.reader.read_json -> module.pipeline.run_pipeline
              -> module.writer.write_json -> 出参 JSON
异常统一转为 resultFlag=0 + errorInfo（接口契约只返回错误消息，不泄漏堆栈）。

新增算法模块：只需在 modules/ 下声明 MODULE（interface_path 非 None），
本中心自动注册其蓝图，无需再改本文件。
"""
import logging

from flask import Blueprint, jsonify, request

from modules import all_modules

logger = logging.getLogger(__name__)


def make_blueprint(module):
    """为单个算法模块生成 Flask 蓝图（路由 = module.interface_path）。

    注意：算法串行同步运行、scheduler 使用模块级全局变量（有状态、非重入）。
    服务以单线程模式启动（server.run_server, threaded=False），
    请求按到达顺序天然串行处理，此处不设计并发/异步。
    """
    bp = Blueprint(module.name, __name__)

    @bp.route(module.interface_path, methods=['POST'])
    def handle_module_request():
        try:
            payload = request.get_json(silent=True) or {}
            if not payload:
                logger.warning("%s 请求体为空或不是合法 JSON", module.display_name)
                return jsonify({'resultFlag': '0', 'errorInfo': '请求体为空或不是合法 JSON'}), 200

            logger.info(
                "收到%s请求: %s",
                module.display_name,
                ', '.join(f"{name}={len(payload.get(name) or [])}" for name in module.input_sets),
            )

            dfs = module.reader.read_json(payload)
            output_dfs = module.pipeline.run_pipeline(dfs)
            result = module.writer.write_json(output_dfs)

            logger.info("%s排程成功，生成 %d 条%s明细",
                        module.display_name,
                        len(result.get(module.output_key) or []),
                        module.output_key)
            return jsonify(result), 200
        except Exception as e:
            logger.exception("%s 排程处理异常", module.display_name)
            return jsonify({'resultFlag': '0', 'errorInfo': str(e)}), 200

    return bp


def register_blueprints(app) -> None:
    """为全部已接入 HTTP 的算法模块注册蓝图。"""
    for module in all_modules():
        if not module.is_http():
            logger.info("模块 %s 未接入 HTTP，跳过", module.display_name)
            continue
        bp = make_blueprint(module)
        app.register_blueprint(bp)
        logger.info("注册蓝图: %s (%s)", bp.name, module.interface_path)
