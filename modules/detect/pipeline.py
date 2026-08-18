"""
检定排程 — 统一执行流水线
==========================
run_pipeline()：数据准备 → 主调度 → 输出构建 三步串起来，
CLI（Excel 兑底）与 HTTP（接口 JSON）两条路径共用同一函数，
保证命令行调用与 HTTP 调用的行为完全一致。

    process_data(dfs)                    -> 填充 scheduler 全局变量
    scheduler.run_scheduling()           -> 填充 chamber_time / schedule_details
    scheduler.build_output_dataframes()  -> 产出 {key: DataFrame}
"""
from __future__ import annotations

import logging
import time
from typing import Dict

import pandas as pd

from . import scheduler
from .constants import SchedulingConfig
from .prepare import process_data

logger = logging.getLogger(__name__)


def run_pipeline(dfs: Dict[str, pd.DataFrame],
                 sched_cfg: SchedulingConfig = None) -> Dict[str, pd.DataFrame]:
    """执行完整排程流水线，返回输出 DataFrame 字典。

    :param dfs:        reader 读出的 12 个 key 的 DataFrame
    :param sched_cfg:  算法默认参数；缺省使用 SchedulingConfig() 默认值
    :return:           build_output_dataframes 产出的 {key: DataFrame}

    日志约定：INFO 记录三个阶段里程碑与耗时，DEBUG 记录输出明细规模。
    """
    if sched_cfg is None:
        sched_cfg = SchedulingConfig()
        logger.debug("未显式指定算法参数，使用 SchedulingConfig 默认值")

    logger.info("========== 排程流水线开始 ==========")
    t0 = time.time()
    logger.info("【阶段 1/3】数据准备（process_data）开始")
    process_data(dfs, sched_cfg)
    logger.info("【阶段 1/3】数据准备完成，耗时 %.2fs", time.time() - t0)

    t0 = time.time()
    logger.info("【阶段 2/3】主调度（run_scheduling）开始")
    scheduler.run_scheduling()
    logger.info("【阶段 2/3】主调度完成：生成 %d 个检定子任务，总计 %d 台，耗时 %.2fs",
                len(scheduler.schedule_details),
                sum(d['每批数量'] for d in scheduler.schedule_details),
                time.time() - t0)

    t0 = time.time()
    logger.info("【阶段 3/3】输出构建（build_output_dataframes）开始")
    output_dfs = scheduler.build_output_dataframes(dfs['arrival'], dfs['unqualified'])
    for key, df in output_dfs.items():
        logger.debug("  输出 [%s]：%d 行", key, 0 if df is None else len(df))
    logger.info("【阶段 3/3】输出构建完成，耗时 %.2fs", time.time() - t0)
    logger.info("========== 排程流水线结束 ==========")
    return output_dfs
