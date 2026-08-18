"""
检定排程 — 数据写入适配
========================
把 build_output_dataframes() 产出的 {key: DataFrame} 适配成两种输出格式：
- write_excel : 写入 Excel 多 sheet（离线兑底 / 开发验证），返回输出文件路径
- write_json  : 构造成接口文档（接口说明v2.0）定义的出参 JSON（生产环境），返回出参字典

不做多余封装，只做格式适配 + 异常处理。
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

from .constants import DEMAND_FLAG_YES, DEMAND_FLAG_NO


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


def _fmt_code(value) -> str:
    """码值 -> 2 位零填充字符串（接口格式 '01' / '19'）；空值 -> ''。

    出参 equipCls / equipCateg / deviceType 均要求 VW_* 编码的零填充字符串
    （8.16 输出行的 设备分类编码 / 设备类别编码 / 检定仓类型编码 为 int 码）。
    """
    if value is None or pd.isna(value):
        return ''
    if isinstance(value, (int, np.integer)):
        return f"{int(value):02d}"
    if isinstance(value, (float, np.floating)):
        return f"{int(value):02d}" if float(value).is_integer() else str(float(value))
    return str(value).strip()


def _fmt_dt(value) -> str:
    """时间 -> 'yyyy-MM-dd HH:mm:ss'；空值 -> ''。"""
    if value is None or pd.isna(value):
        return ''
    return pd.Timestamp(value).strftime('%Y-%m-%d %H:%M:%S')


def _fmt_scheme_id(value):
    """detectSchemeId -> int（接口 NUMBER 类型）；空值/NaN -> ''。

    8.17 起算法输出行携带 检测方案标识（spec.参数标识）；查不到的设备码
    返回空串（与 8.17 原脚本一致）。
    """
    if value is None or value == '' or (isinstance(value, float) and pd.isna(value)):
        return ''
    try:
        return int(value)
    except (ValueError, TypeError):
        return ''


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
    demand_flag = _safe_str(_row_get(row, '是否为需求优先'))
    return {
        'sysNo': _safe_str(_row_get(row, '检定线ID')),
        'sysName': _safe_str(_row_get(row, '检定线名称')),
        # 检定仓类型编码：8.16 起直接取 检定仓类型编码（VW_DEVICE_TYPE 码 1-9），
        # 替代原先的仓类型名称→码反查（仓类型名称有三套口径，反查不可靠）
        'deviceType': _fmt_code(_row_get(row, '检定仓类型编码')),
        'deviceNo': _safe_str(_row_get(row, '检定仓编号')),
        'arriveBatchNo': _safe_str(_row_get(row, '到货批次号')),
        # 设备类别编码：8.16 补缺口（1电能表 / 2互感器 / 9计量自动化终端）
        'equipCateg': _fmt_code(_row_get(row, '设备类别编码')),
        # 设备分类编码（VW_EQUIP_CLS）：8.16 起由中文名改输出码（对齐接口 v2.0 出参定义）
        'equipCls': _fmt_code(_row_get(row, '设备分类编码')),
        'equipCode': _safe_str(_row_get(row, '设备码')),
        'equipDesc': '',                        # 待企业确认字段口径
        # 8.11 已生产"目标设备类型码"：需求设备=自身码，非需求设备=分配目标码（v2.0 §1.3）
        'aimEquipCode': _safe_str(_row_get(row, '目标设备类型码')),
        # 检定方案标识：8.17 起从 spec.参数标识 取（含大小码回退），查不到返空串
        'detectSchemeId': _fmt_scheme_id(_row_get(row, 'detectSchemeId')),
        'projectedStartTime': _fmt_dt(_row_get(row, '预计开始时间')),
        'projectedEndTime': _fmt_dt(_row_get(row, '预计完成时间')),
        'detectPlanQty': int(_row_get(row, '每批数量') or 0),
        # 是否为需求优先：8.16 起算法输出 1/0（VW_YES_NO_FLAG），直读映射
        'demandFlag': DEMAND_FLAG_YES if demand_flag == '1' else DEMAND_FLAG_NO,
        'weekDayStartAndEnd': '',               # 待企业确认字段口径
    }


def write_json(output_dfs: Dict[str, pd.DataFrame]) -> dict:
    """把排程明细构造成接口文档的出参 JSON 字典。

    数据来源：output_dfs['details_sorted']（检定时间明细 DataFrame），
    每一行对应一条 detectPlanSchedulingchList 记录；无明细时返回空表。

    当前对接口要求但算法不生产的字段（equipDesc / weekDayStartAndEnd）
    先返回空字符串，待企业确认字段口径后再补齐；detectSchemeId 自 8.17 起
    由 spec.参数标识 生产（查不到返空串）。
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
