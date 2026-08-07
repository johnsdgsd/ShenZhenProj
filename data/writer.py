"""
数据写入适配
============
把 build_output_dataframes() 产出的 {key: DataFrame} 适配成两种输出格式：
- write_excel : 写入 Excel 多 sheet（离线兑底 / 开发验证），返回输出文件路径
- write_json  : 构造成接口文档（接口说明.md）定义的出参 JSON（生产环境），返回出参字典

不做多余封装，只做格式适配 + 异常处理。
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

from .constants import DEVICE_TYPE_MAP, DEMAND_FLAG_YES, DEMAND_FLAG_NO

# 检定仓类型 名称 -> 编码 反向映射（出参 deviceType 要求 VW_DEVICE_TYPE 编码）
_DEVICE_TYPE_REV = {v: k for k, v in DEVICE_TYPE_MAP.items()}


# ==================================================================
# 出参 JSON 适配辅助函数
# ==================================================================

def _safe_str(value) -> str:
    """任意值转字符串；NaN/None -> ''；整数型浮点（123.0）去掉 .0。"""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ''
    if isinstance(value, str):
        return value
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return str(int(value)) if float(value).is_integer() else str(float(value))
    return str(value)


def _fmt_dt(value) -> str:
    """时间 -> 'yyyy-MM-dd HH:mm:ss'；空值 -> ''。"""
    if value is None or pd.isna(value):
        return ''
    return pd.Timestamp(value).strftime('%Y-%m-%d %H:%M:%S')


def _row_get(row: pd.Series, key: str):
    return row[key] if key in row.index else None


# ==================================================================
# Excel 实现（离线兑底）
# ==================================================================

def write_excel(output_dfs: Dict[str, pd.DataFrame],
                output_path: Path,
                sheet_names: Dict[str, str]) -> Path:
    """把输出 DataFrame 写入 Excel 多 sheet，返回输出文件路径。

    缺失或空的 DataFrame 跳过（warning 提示），保证排程为空时也能正常落盘。
    """
    output_path = Path(output_path)
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        for key, sheet in sheet_names.items():
            df = output_dfs.get(key)
            if df is None or df.empty:
                warnings.warn(f"缺少输出数据 key: {key}，跳过 sheet「{sheet}」")
                continue
            df.to_excel(writer, sheet_name=sheet, index=False)
    return output_path


# ==================================================================
# JSON 实现（接口文档出参）
# ==================================================================

def _to_api_row(row: pd.Series) -> dict:
    device_type_name = _safe_str(_row_get(row, '检定仓类型'))
    demand_flag = _safe_str(_row_get(row, '是否为需求优先'))
    return {
        'sysNo': _safe_str(_row_get(row, '检定线ID')),
        'sysName': _safe_str(_row_get(row, '检定线名称')),
        'deviceType': _DEVICE_TYPE_REV.get(device_type_name, device_type_name),
        'deviceNo': _safe_str(_row_get(row, '检定仓编号')),
        'arriveBatchNo': _safe_str(_row_get(row, '到货批次号')),
        'equipCateg': '',                       # 待企业确认字段口径
        'equipCls': _safe_str(_row_get(row, '设备类型')),
        'equipCode': _safe_str(_row_get(row, '设备码')),
        'equipDesc': '',                        # 待企业确认字段口径
        'detectSchemeId': '',                   # 待企业确认字段口径
        'projectedStartTime': _fmt_dt(_row_get(row, '预计开始时间')),
        'projectedEndTime': _fmt_dt(_row_get(row, '预计完成时间')),
        'detectPlanQty': int(_row_get(row, '每批数量') or 0),
        'demandFlag': DEMAND_FLAG_YES if demand_flag == '是' else DEMAND_FLAG_NO,
        'weekDayStartAndEnd': '',               # 待企业确认字段口径
    }


def write_json(output_dfs: Dict[str, pd.DataFrame]) -> dict:
    """把排程明细构造成接口文档的出参 JSON 字典。

    数据来源：output_dfs['details_sorted']（检定时间明细 DataFrame），
    每一行对应一条 detectPlanSchedulingchList 记录；无明细时返回空表。

    当前对接口要求但算法不生产的字段（equipCateg / equipDesc /
    detectSchemeId / weekDayStartAndEnd）先返回空字符串，
    待企业确认字段口径后再补齐。
    """
    detail_df = output_dfs.get('details_sorted')
    rows = []
    if detail_df is not None and not detail_df.empty:
        for _, row in detail_df.iterrows():
            rows.append(_to_api_row(row))
    return {
        'resultFlag': '1',
        'errorInfo': '',
        'detectPlanSchedulingchList': rows,
    }
