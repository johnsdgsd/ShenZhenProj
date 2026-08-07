"""
算法默认参数
============
SchedulingConfig 对应原脚本 `检定排程python代码最新8.03.py` 中散落的硬编码值。
不属于环境配置，因此放在算法包内，而非顶层 config.py。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Tuple


@dataclass
class SchedulingConfig:
    """调度算法默认参数。"""
    default_times: Dict[str, int] = field(default_factory=lambda: {
        '三相电能表': 414,
        '单相电能表': 108,
        '智能量测终端': 414,
        '10kV电压互感器': 25,
        '20kV电压互感器': 25,
        '10kV电流互感器': 25,
        '20kV电流互感器': 25,
        '低压电流互感器': 25,
    })
    default_gap_minutes: float = 5.0          # 调度时间间隔（分钟）
    default_base_date: datetime = datetime(2026, 3, 1, 9, 0, 0)
    default_work_start: Tuple[int, int] = (9, 0)    # 默认上班时间
    default_work_end: Tuple[int, int] = (17, 0)     # 默认下班时间
    max_day_search: int = 365 * 10                  # 最大搜索天数，防止死循环
