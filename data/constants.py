"""
数据处理层常量
==============
接口文档（接口说明.md）的视图枚举字典 + Excel 兑底模式的 sheet 映射。
不放入顶层 config.py —— 那里只做环境配置。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

# ==================================================================
# 接口文档枚举字典（来自 接口说明.md 的"视图枚举字典"章节）
# ==================================================================

# VW_DETECT_EQUIP_TYPE：所检设备表类型 编码 → 名称
DETECT_EQUIP_TYPE_MAP: Dict[str, str] = {
    '01': '单相电能表',
    '02': '三相直接表',
    '03': '三相互感表',
    '04': '10kV电压互感器',
    '05': '20kV电压互感器',
    '06': '10kV电流互感器',
    '07': '20kV电流互感器',
    '08': '普通型低压电流互感器',
    '09': '大变比型低压电流互感器',
    '10': 'DBI型低压电流互感器',
    '11': '经互感器接入集中器',
    '12': '经互感器接入负荷管理终端',
    '13': '经互感器接入配变监测计量终端',
    '14': '经互感器接入智能量测终端',
    '15': '直接接入集中器',
    '16': '直接接入负荷管理终端',
    '17': '直接接入配变监测计量终端',
    '18': '直接接入智能量测终端',
}

# VW_DEVICE_TYPE：检定仓类型 编码 → 名称
DEVICE_TYPE_MAP: Dict[str, str] = {
    '01': '单相电能表检定仓',
    '02': '单三相兼容检定仓',
    '03': '终端检定仓',
    '04': '三相电能表检定仓',
    '05': '三相表兼容终端检定仓',
    '06': '10kv/20kv电压兼容仓',
    '07': '10kv/20kv电流兼容仓',
    '08': '普通型低压电流互感器/大变比型低压电流互感器兼容仓',
    '09': '普通型低压电流互感器/DBI型低压电流互感器兼容仓',
}

# 接入方式推断：接口入参没有"接入方式"字段，只能从所检设备表类型编码推断
# 编码 11-14 = 经互感器接入；15-18 = 直接接入
HUGAN_ACCESS_CODES = {'11', '12', '13', '14'}

# 出参：是否为需求优先 编码（VW_YES_NO_FLAG）
DEMAND_FLAG_YES = '1'
DEMAND_FLAG_NO = '0'


# ==================================================================
# Excel 兑底模式数据源参数
# ==================================================================

@dataclass
class DataSourceConfig:
    """Excel 兑底模式数据源参数（离线开发/验证用）。"""
    output_path: Path = Path('检定排程计划_优化版_无加班.xlsx')
    input_sheet_names: Dict[str, str] = field(default_factory=lambda: {
        'overall': '整体情况',
        'line_info': '检定线信息表',
        'chamber_type': '检定仓类型表',
        'chamber_config': '检定仓配置表',
        'arrival': '到货排程-到货计划旧表',
        'demand': '需求明细',
        'spec': '规格设备码信息表',
        'qualified': '合格品库存信息表',
        'unqualified': '非合格品库存',
        'time_config': '排程时间配置',
        'gap_config': '调度时间间隔配置',
    })
    output_sheet_names: Dict[str, str] = field(default_factory=lambda: {
        'schedule_summary': '检定排程明细',
        'details_sorted': '检定时间明细',
        'util': '仓利用率统计',
        'batch_alloc': '到货批次分配明细',
        'original': '原始到货批次',
        'demand_summary': '月度需求汇总',
        'chamber_config': '检定仓配置',
    })
