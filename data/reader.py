"""
数据读取适配
============
把两种输入格式统一适配成算法期望的 11 个 DataFrame：
- read_excel : 读取 Excel 文件（离线兑底 / 开发验证）
- read_json  : 解析接口文档（接口说明.md）定义的 8 个 JSON 入参集合（生产环境）

不做多余封装，只做格式适配 + 异常处理。两种实现返回**同构**的
{key: DataFrame} —— key 与列名均与 algorithm/prepare.py 的 process_data()
期望一致，因此核心算法对两条路径完全复用。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd

from .constants import (
    DETECT_EQUIP_TYPE_MAP,
    DEVICE_TYPE_MAP,
    HUGAN_ACCESS_CODES,
)


# ==================================================================
# 接口数据 -> Excel 等价列 的适配辅助函数
# ==================================================================

def _equip_type_name(code):
    """所检设备表类型编码 -> 名称；若已是名称则原样返回。"""
    if code is None or pd.isna(code):
        return None
    code = str(code).strip()
    return DETECT_EQUIP_TYPE_MAP.get(code, code)


def _device_type_name(code):
    """检定仓类型编码 -> 名称；若已是名称则原样返回。"""
    if code is None or pd.isna(code):
        return None
    code = str(code).strip()
    return DEVICE_TYPE_MAP.get(code, code)


def _infer_category(equip_type_code_or_name):
    """从所检设备表类型推断设备分类。

    接口入参的 detectEquipType 是编码（01-18），先经 VW_DETECT_EQUIP_TYPE
    转为名称，再做与 common.utils.parse_device_category 一致的关键词匹配。
    返回 8 种设备分类之一；无法识别返回 None。
    """
    name = _equip_type_name(equip_type_code_or_name)
    if not name:
        return None
    desc = name.lower()
    if '单相电能表' in desc:
        return '单相电能表'
    if '三相直接' in desc or '三相互感' in desc:
        return '三相电能表'
    if any(k in desc for k in ('集中器', '负荷控制终端', '负荷管理终端',
                               '配变监测终端', '智能量测终端', '厂站终端')):
        return '智能量测终端'
    if '10kv电压互感器' in desc:
        return '10kV电压互感器'
    if '20kv电压互感器' in desc:
        return '20kV电压互感器'
    if '10kv电流互感器' in desc:
        return '10kV电流互感器'
    if '20kv电流互感器' in desc:
        return '20kV电流互感器'
    if '低压电流互感器' in desc:
        return '低压电流互感器'
    return None


# 算法认可的设备分类中文名（与 algorithm 内 parse_device_category 的产出集合一致）。
# 用于判断 equipCls 值是否已是"可直接被算法使用"的分类名，而非未定义口径的编码。
_KNOWN_CATEGORIES = {
    '单相电能表', '三相电能表', '智能量测终端',
    '10kV电压互感器', '20kV电压互感器', '10kV电流互感器', '20kV电流互感器',
    '低压电流互感器',
}


def _infer_access(equip_type_code):
    """从所检设备表类型编码推断接入方式（'经互感接入' / '直接接入'）。

    接口入参没有"接入方式"字段，编码 11-14 为经互感系列，15-18 为直接接入系列。
    """
    if equip_type_code is None or pd.isna(equip_type_code):
        return ''
    code = str(equip_type_code).strip()
    if code in HUGAN_ACCESS_CODES:
        return '经互感接入'
    if code in DETECT_EQUIP_TYPE_MAP:
        return '直接接入'
    return ''


def _parse_dt(value):
    """把接口字符串时间（yyyy-MM-dd HH:mm:ss）解析为 Timestamp；空值返回 NaT。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NaT
    if isinstance(value, pd.Timestamp):
        return value
    if hasattr(value, 'hour'):
        return pd.Timestamp(value)
    return pd.to_datetime(str(value), errors='coerce')


def _to_int(value):
    """接口编号字段转 int（与 Excel 路径的 int 类型保持一致，保证字典 key 匹配）。"""
    if value is None or pd.isna(value):
        return None
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return str(value).strip()


# ==================================================================
# Excel 实现（离线兑底）
# ==================================================================

def read_excel(file_path: Path, sheet_names: Dict[str, str]) -> Dict[str, pd.DataFrame]:
    """读取 Excel 文件 11 个 sheet，返回 {key: DataFrame}。

    文件不存在抛 FileNotFoundError；缺少必需 sheet 抛 ValueError（带 sheet 名）。
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {file_path}")
    dfs = {}
    for key, sheet in sheet_names.items():
        try:
            dfs[key] = pd.read_excel(file_path, sheet_name=sheet)
        except ValueError as e:
            raise ValueError(f"Excel 缺少必需 sheet「{sheet}」（内部 key: {key}）: {e}") from e
    return dfs


# ==================================================================
# JSON 实现（接口文档入参）
# ==================================================================
# 入参集合 -> 内部 DataFrame 的对应关系：
#   deviceParaList    -> overall / line_info / chamber_type / chamber_config
#   dmdPlanDetList    -> demand / spec
#   arriveBatchList   -> arrival / spec
#   detectSchList     -> spec
#   qualifiedStockList-> qualified
#   unqualifiedStockList -> unqualified
#   scheduleTimeList  -> time_config
#   scheduleConfigList-> gap_config / line_info

# 每个内部 key 对应的列名（与 Excel sheet 列名一致，保证空数据也有正确结构）
_COLS = {
    'overall': ['线体编号', '线体名称', '检定仓编号', '检定仓类型', '所检设备表类型', '表位数'],
    'line_info': ['检定线ID', '检定线名称'],
    'chamber_type': ['仓类型ID', '仓类型名称'],
    'chamber_config': ['检定线ID', '检定仓编号', '仓类型ID'],
    'arrival': ['到货批次号', '设备分类', '设备规格', '数量', '预计到货日期'],
    'demand': ['所属月份', '设备类型码大码', '申请数量'],
    'spec': ['设备码', '设备分类', '接入方式', '自动检定时间'],
    'qualified': ['设备码', '合格品库存', '未配送库存', '安全库存'],
    'unqualified': ['到货批次号', '设备类型码', '设备分类', '可检库存'],
    'time_config': ['工作日日期', '开始时间', '结束时间'],
    'gap_config': ['线体编号', '调度时间间隔（秒）'],
}


def _get(data: dict, key: str) -> list:
    return data.get(key) or []


def _frame(key: str, rows: list) -> pd.DataFrame:
    """按固定列名构造 DataFrame，空数据也保留列结构。"""
    return pd.DataFrame(rows, columns=_COLS[key])


def _build_overall(data) -> pd.DataFrame:
    rows = []
    for r in _get(data, 'deviceParaList'):
        rows.append({
            '线体编号': _to_int(r.get('sysNo')),
            '线体名称': r.get('sysName'),
            '检定仓编号': str(r.get('deviceNo')) if r.get('deviceNo') is not None else None,
            '检定仓类型': _device_type_name(r.get('deviceType')),
            '所检设备表类型': _equip_type_name(r.get('detectEquipType')),
            '表位数': r.get('posNum'),
        })
    return _frame('overall', rows)


def _build_line_info(data) -> pd.DataFrame:
    # 线体名称同时出现在 deviceParaList 与 scheduleConfigList，合并去重
    mapping = {}
    for r in _get(data, 'deviceParaList'):
        if r.get('sysNo') is not None:
            mapping[_to_int(r['sysNo'])] = str(r.get('sysName') or '').strip()
    for r in _get(data, 'scheduleConfigList'):
        if r.get('sysNo') is not None:
            mapping[_to_int(r['sysNo'])] = str(r.get('sysName') or '').strip()
    rows = [{'检定线ID': k, '检定线名称': v} for k, v in mapping.items()]
    return _frame('line_info', rows)


def _build_chamber_type(data) -> pd.DataFrame:
    rows = [{'仓类型ID': int(k), '仓类型名称': v} for k, v in DEVICE_TYPE_MAP.items()]
    return _frame('chamber_type', rows)


def _build_chamber_config(data) -> pd.DataFrame:
    seen = set()
    rows = []
    for r in _get(data, 'deviceParaList'):
        if r.get('sysNo') is None or r.get('deviceNo') is None:
            continue
        key = (_to_int(r['sysNo']), str(r['deviceNo']))
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            '检定线ID': _to_int(r['sysNo']),
            '检定仓编号': str(r['deviceNo']),
            '仓类型ID': _to_int(r['deviceType']),
        })
    return _frame('chamber_config', rows)


def _build_arrival(data) -> pd.DataFrame:
    rows = []
    for r in _get(data, 'arriveBatchList'):
        rows.append({
            '到货批次号': r.get('arriveBatchNo'),
            '设备分类': r.get('equipCls'),
            '设备规格': r.get('equipCode'),
            '数量': r.get('arriveQty'),
            '预计到货日期': _parse_dt(r.get('arriveDate')),
        })
    return _frame('arrival', rows)


def _build_demand(data) -> pd.DataFrame:
    rows = []
    for r in _get(data, 'dmdPlanDetList'):
        year = str(r.get('planYear') or '')
        month2 = str(r.get('planMonth') or '')
        month = year + month2.zfill(2) if year else month2
        rows.append({
            '所属月份': month,
            # 需求用"设备类型码大码"聚合；缺省时回退到设备类型码
            '设备类型码大码': r.get('pEquipCode') or r.get('equipCode'),
            '申请数量': r.get('sumQty'),
        })
    return _frame('demand', rows)


def _build_spec(data) -> pd.DataFrame:
    """规格设备码信息表：由 detectSchList + 需求/到货 跨集合聚合合成。

    - 设备码/自动检定时间   <- detectSchList (equipCode / schTime)
    - 设备分类             <- 优先按 detectEquipType 推断（接口枚举有文档、可靠，
                               能推出算法认可的中文分类名）；equipCls 在接口入参中
                               是编码（"01"/"06"…，接口文档未定义其枚举），无法直接
                               匹配算法分类名，仅在 equipCls 已是中文分类名时兜底
    - 接入方式             <- 由 detectEquipType 编码推断（接口无此字段）
    """
    cls_map, etype_map = {}, {}
    for r in list(_get(data, 'dmdPlanDetList')) + list(_get(data, 'arriveBatchList')):
        code = r.get('equipCode')
        if code is None or pd.isna(code):
            continue
        code = str(code).strip()
        if r.get('equipCls') is not None and pd.notna(r.get('equipCls')):
            cls_map[code] = str(r['equipCls']).strip()
        if r.get('detectEquipType') is not None:
            etype_map[code] = str(r['detectEquipType']).strip()

    sch_time = {}
    for r in _get(data, 'detectSchList'):
        code = r.get('equipCode')
        if code is None or pd.isna(code):
            continue
        code = str(code).strip()
        if r.get('schTime') is not None and pd.notna(r.get('schTime')):
            sch_time[code] = int(r['schTime'])

    rows = []
    for code in sorted(set(cls_map) | set(etype_map) | set(sch_time)):
        # 设备分类：优先按 detectEquipType 推断（枚举有文档，推出中文分类名，
        # 与算法 chambers 的容量 key 匹配）；equipCls 在接口入参中多为编码，
        # 仅当其已是中文分类名时兜底采用（兼容测试/兑底数据）。
        cat = _infer_category(etype_map.get(code))
        if not cat:
            raw_cls = cls_map.get(code)
            cat = raw_cls if raw_cls in _KNOWN_CATEGORIES else None
        rows.append({
            '设备码': code,
            '设备分类': cat,
            '接入方式': _infer_access(etype_map.get(code)),
            '自动检定时间': sch_time.get(code),
        })
    return _frame('spec', rows)


def _build_qualified(data) -> pd.DataFrame:
    rows = []
    for r in _get(data, 'qualifiedStockList'):
        rows.append({
            '设备码': r.get('equipCode'),
            '合格品库存': r.get('qualifiedQty'),
            '未配送库存': r.get('distLockQty'),
            '安全库存': r.get('lowerLimitQty'),
        })
    return _frame('qualified', rows)


def _build_unqualified(data) -> pd.DataFrame:
    rows = []
    for r in _get(data, 'unqualifiedStockList'):
        rows.append({
            '到货批次号': r.get('arriveBatchNo'),
            '设备类型码': r.get('equipCode'),
            '设备分类': r.get('equipCls'),
            '可检库存': r.get('detectUQty'),
        })
    return _frame('unqualified', rows)


def _build_time_config(data) -> pd.DataFrame:
    rows = []
    for r in _get(data, 'scheduleTimeList'):
        rows.append({
            '工作日日期': _parse_dt(r.get('workDay')),
            '开始时间': r.get('startTime'),
            '结束时间': r.get('endTime'),
        })
    return _frame('time_config', rows)


def _build_gap_config(data) -> pd.DataFrame:
    rows = []
    for r in _get(data, 'scheduleConfigList'):
        rows.append({
            '线体编号': r.get('sysNo'),
            '调度时间间隔（秒）': r.get('timeInterval'),
        })
    return _frame('gap_config', rows)


def read_json(json_data: dict) -> Dict[str, pd.DataFrame]:
    """解析接口文档 8 个 JSON 入参集合，转换为与 Excel 同列的 11 个 DataFrame。

    json_data 为空或非 dict 时抛 ValueError（服务层已把空请求体挡在路由外，
    此处兜底防御）。
    """
    if json_data is None:
        json_data = {}
    if not isinstance(json_data, dict):
        raise ValueError(f"入参必须是 JSON 对象，实际类型: {type(json_data).__name__}")

    return {
        'overall': _build_overall(json_data),
        'line_info': _build_line_info(json_data),
        'chamber_type': _build_chamber_type(json_data),
        'chamber_config': _build_chamber_config(json_data),
        'arrival': _build_arrival(json_data),
        'demand': _build_demand(json_data),
        'spec': _build_spec(json_data),
        'qualified': _build_qualified(json_data),
        'unqualified': _build_unqualified(json_data),
        'time_config': _build_time_config(json_data),
        'gap_config': _build_gap_config(json_data),
    }
