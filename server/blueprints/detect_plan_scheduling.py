"""
检定计划排程接口（detectPlanScheduling）蓝图
============================================
本模块只做**接口暴露 + 调用算法**：
- 解析 HTTP 请求 JSON 入参
- 调用统一流水线 algorithm.pipeline.run_pipeline()
- 把输出 DataFrame 交给 data.writer.write_json() 构造成出参 JSON
- 异常统一转为 resultFlag=0 + errorInfo

接口路径为接口文档（接口说明.md）定义的固定常量。

注意：算法**串行同步运行**，且 scheduler 使用模块级全局变量（有状态、非重入）。
因此不设计并发/异步，服务以单线程模式启动（见 server.run_server），
请求按到达顺序天然串行处理。
"""
import logging

from flask import Blueprint, jsonify, request

from algorithm.constants import SchedulingConfig
from algorithm.pipeline import run_pipeline
from data.reader import read_json
from data.writer import write_json

logger = logging.getLogger(__name__)

# 接口文档定义的接口路径
INTERFACE_PATH = '/restful/busiInterface/ipsService/detectPlanScheduling'

bp = Blueprint('detect_plan_scheduling', __name__)

# 算法默认参数（可单例复用，process_data 每次都会重新填充 scheduler 全局变量）
_sched_cfg = SchedulingConfig()

# 入参 8 个集合名（仅用于日志统计）
_INPUT_SETS = (
    'deviceParaList', 'dmdPlanDetList', 'arriveBatchList', 'detectSchList',
    'qualifiedStockList', 'unqualifiedStockList', 'scheduleTimeList', 'scheduleConfigList',
)


@bp.route(INTERFACE_PATH, methods=['POST'])
def detect_plan_scheduling():
    try:
        payload = request.get_json(silent=True) or {}
        if not payload:
            logger.warning("请求体为空或不是合法 JSON")
            return jsonify({'resultFlag': '0', 'errorInfo': '请求体为空或不是合法 JSON'}), 200

        logger.info(
            "收到排程请求: %s",
            ', '.join(f"{name}={len(payload.get(name) or [])}" for name in _INPUT_SETS),
        )

        dfs = read_json(payload)
        output_dfs = run_pipeline(dfs, _sched_cfg)
        result = write_json(output_dfs)

        logger.info("排程成功，生成 %d 条检定计划明细",
                    len(result.get('detectPlanSchedulingchList') or []))
        return jsonify(result), 200
    except Exception as e:
        logger.exception("排程处理异常")
        return jsonify({'resultFlag': '0', 'errorInfo': str(e)}), 200
