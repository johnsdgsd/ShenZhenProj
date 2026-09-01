"""到货计划排程三阶段流水线。"""
from __future__ import annotations

import logging
import time
from typing import Dict

import pandas as pd

from .models import ArrivalResult
from .prepare import process_data
from .scheduler import run_scheduling

logger = logging.getLogger(__name__)


def run_pipeline(dfs: Dict[str, pd.DataFrame]) -> ArrivalResult:
    started = time.perf_counter()
    logger.info('========== 到货排程流水线开始 ==========')
    prepared = process_data(dfs)
    result = run_scheduling(prepared)
    logger.info(
        '到货排程完成：计划=%d 容量告警=%d 合同分配=%d 合同不足=%d 净需求=%d，耗时 %.3fs',
        len(result.schedule_rows), len(result.capacity_alarm_rows),
        len(result.contract_allocation_rows), len(result.contract_shortage_rows),
        len(result.net_demand_rows), time.perf_counter() - started,
    )
    logger.info('========== 到货排程流水线结束 ==========')
    return result
