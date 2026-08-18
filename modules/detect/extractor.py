"""
接口数据提取器（V2.0）
======================
职责边界：我方只负责「从接口拿数据 + 把算法数据返回接口」，
中间处理归算法负责人。本模块只做**提取**，不加工——

- 把接口请求 JSON 的 9 个集合原样提取为 DataFrame（字段用接口文档 V2.0 的英文名）
- 把接口文档「二、系统字典视图」的码值映射硬编码为字典，并同时提取为 DataFrame
- 统一入口 `extract_request(payload)` 返回全部 DataFrame（请求数据 + 码值映射）
- 不做任何业务推断：不翻译码值、不推断接入方式、不做分配计算、不换算单位

兼容真实报文与文档的差异：
- 第 9 集合双别名：`nonDmdAimEquipCodeCfgList`（文档）/ `nonDmdTargetEquipCodeCfgVOList`（报文）
- 字段双别名：`allocationRatio`（文档）/ `allocationRation`（报文）
- 字段大小写：`pEquipCode`（文档）/ `pequipCode`（报文）
- 到货日期 Java 格式：`Wed Aug 05 00:00:00 CST 2026`（ISO 格式兜底）
- 时间未补零（`9:00`）、空串 / null 归一为 NaN、空集合保列结构
"""
from __future__ import annotations

import re
from typing import Dict, List

import numpy as np
import pandas as pd

# ==================================================================
# 硬编码码值映射 —— 接口文档 V2.0「二、系统字典视图」
# （键为编码字符串，保留前导 0；后续客户补充码值数据在此追加即可）
# ==================================================================

# VW_DETECT_EQUIP_TYPE：所检设备表类型 编码 → 名称
DETECT_EQUIP_TYPE_DICT: Dict[str, str] = {
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

# VW_DEVICE_TYPE：检定仓类型 编码 → 名称（以 V2.0 文档为准）
DEVICE_TYPE_DICT: Dict[str, str] = {
    '01': '单相电能表检定仓',
    '02': '单三相兼容检定仓',
    '03': '终端检定仓',
    '04': '三相电能表检定仓',
    '05': '三相表兼容终端检定仓',
    '06': '10kv/20kv电压兼容仓',
    '07': '10kv/20kv电流兼容仓',
    '08': '普通/大变比低压CT兼容仓',
    '09': '普通/DBI低压CT兼容仓',
}

# VW_YES_NO_FLAG：是否标志
YES_NO_FLAG_DICT: Dict[str, str] = {
    '0': '否',
    '1': '是',
}

# VW_EQUIP_CLS：设备分类（V2.0 新增）
EQUIP_CLS_DICT: Dict[str, str] = {
    '01': '单相电能表',
    '02': '三相电能表',
    '03': '负荷管理终端',
    '04': '集中器',
    '05': '配变监测计量终端',
    '06': '10kV电流互感器',
    '07': '10kV电压互感器',
    '08': '低压电流互感器',
    '09': '组合互感器',
    '10': '厂站终端',
    '11': '通信模块',
    '19': '智能量测终端',
    '20': '20kV电流互感器',
    '21': '20kV电压互感器',
    '23': '周转箱',
    '24': '栈板',
    '31': '单相计量表箱',
    '32': '10kV低压计量表箱',
    '33': '三相计量表箱',
    '34': '10kV高压计量表箱',
    '35': '单相费控计量表箱',
    '36': '三相费控计量表箱',
    '37': '集中器箱',
    '41': '运行封印',
    '42': '端子盖',
}

# VW_EQUIP_CATEG：设备类别（V2.0 新增）
EQUIP_CATEG_DICT: Dict[str, str] = {
    '01': '电能表',
    '02': '互感器',
    '09': '计量自动化终端',
    '10': '计量表箱',
    '15': '通信模块',
    '17': '封印',
    '18': '开关',
    '19': '周转箱',
    '21': '配件',
    '78': '栈板',
}

# VW_DETECT_TYPE：检定类别（V2.0 新增）
DETECT_TYPE_DICT: Dict[str, str] = {
    '01': '全性能试验',
    '02': '到货后抽样检测',
    '03': '首次检定',
    '04': '不合格设备复检',
    '05': '流水线适应性检查',
    '07': '库存复检',
    '11': '临时检定-委托',
    '12': '临时检定-厂返退还',
    '13': '计量标准设备检定/校准',
    '14': '运行抽检',
    '20': '到货后全性能试验',
    '21': '样品比对',
    '22': '解密',
    '50': '期间核查',
    '51': '重复性试验',
    '52': '稳定性考核',
    '53': '量值溯源',
    '54': '测试设备监测/校准',
    '55': '分拣鉴定',
}

# VW_DMD_PLAN_TYPE：计划类型（V2.0 新增）
DMD_PLAN_TYPE_DICT: Dict[str, str] = {
    '01': '月计划',
    '02': '紧急计划',
}

# VW_DETECT_EQUIP_TYPE 的「说明」列（文档 2.1 节；其余视图无说明列）
_DETECT_EQUIP_TYPE_NOTE: Dict[str, str] = {
    '01': '',
    '02': '直接接入三相电能表',
    '03': '互感器接入三相电能表',
    '04': '',
    '05': '',
    '06': '',
    '07': '',
    '08': 'TA变比≤2000A',
    '09': 'TA变比＞2000A',
    '10': '抗直流型',
    '11': '',
    '12': '',
    '13': '',
    '14': '',
    '15': '',
    '16': '',
    '17': '',
    '18': '',
}

# 全部字典视图（key 即返回的码值映射 DataFrame 的 key）
_DICT_VIEWS: Dict[str, Dict[str, str]] = {
    'VW_DETECT_EQUIP_TYPE': DETECT_EQUIP_TYPE_DICT,
    'VW_DEVICE_TYPE': DEVICE_TYPE_DICT,
    'VW_YES_NO_FLAG': YES_NO_FLAG_DICT,
    'VW_EQUIP_CLS': EQUIP_CLS_DICT,
    'VW_EQUIP_CATEG': EQUIP_CATEG_DICT,
    'VW_DETECT_TYPE': DETECT_TYPE_DICT,
    'VW_DMD_PLAN_TYPE': DMD_PLAN_TYPE_DICT,
}


# ==================================================================
# 请求集合：文档字段清单（空集合也保列结构）
# ==================================================================

_COLLECTION_COLS: Dict[str, List[str]] = {
    'deviceParaList': ['sysNo', 'sysName', 'deviceType', 'deviceNo',
                       'deviceName', 'detectEquipType', 'posNum'],
    'dmdPlanDetList': ['dmdPlanDetId', 'dmdPlanNo', 'planType', 'planYear',
                       'planMonth', 'appOrg', 'equipCateg', 'equipCls',
                       'equipCode', 'equipDesc', 'pEquipCode', 'sumQty'],
    'arriveBatchList': ['arriveBatchNo', 'equipCateg', 'equipCls',
                        'equipCode', 'equipDesc', 'arriveQty', 'arriveDate',
                        'detectEquipType'],
    'detectSchList': ['equipCode', 'detectType', 'detectSchemeId', 'schTime'],
    'qualifiedStockList': ['equipCode', 'lowerLimitQty', 'qualifiedQty',
                           'distLockQty'],
    'unqualifiedStockList': ['equipCode', 'arriveBatchNo', 'detectUQty'],
    'scheduleTimeList': ['workDay', 'startTime', 'endTime'],
    'scheduleConfigList': ['sysNo', 'sysName', 'timeInterval', 'overtime'],
    'nonDmdAimEquipCodeCfgList': ['equipCode', 'aimEquipCode', 'allocationRatio'],
}

# 第 9 集合别名：文档名 -> （真实报文使用的其他名字）
_COLLECTION_ALIASES: Dict[str, tuple] = {
    'nonDmdAimEquipCodeCfgList': ('nonDmdTargetEquipCodeCfgVOList',),
}

# 字段别名（键为文档名 -> 真实报文字段名）
_FIELD_ALIASES: Dict[str, tuple] = {
    'allocationRatio': ('allocationRation',),
    'pEquipCode': ('pequipCode',),
}

# 类型归类（键为字段名）
_INT_FIELDS = {'dmdPlanDetId', 'detectSchemeId'}
_NUM_FIELDS = {'posNum', 'sumQty', 'arriveQty', 'lowerLimitQty',
               'qualifiedQty', 'distLockQty', 'detectUQty',
               'timeInterval', 'overtime', 'allocationRatio'}
_DT_FIELDS = {'arriveDate'}
_DATE_FIELDS = {'workDay'}
# 其余字段一律按字符串提取（保留前导 0），如 sysNo / deviceNo / equipCode /
# equipCls / equipCateg / detectEquipType / deviceType / planType / detectType /
# aimEquipCode / pEquipCode / sysName / equipDesc / startTime / endTime / schTime 等


# ==================================================================
# 辅助函数
# ==================================================================

# Java Date.toString 格式：Wed Aug 05 00:00:00 CST 2026
_JAVA_DT_RE = re.compile(
    r'^[A-Za-z]{3}\s+([A-Za-z]{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+'
    r'[A-Za-z]{2,5}\s+(\d{4})$'
)


def _get_collection(data: dict, key: str) -> list:
    """按文档集合名取集合，兼容真实报文的别名；缺失返回空列表。"""
    if isinstance(data, dict):
        val = data.get(key)
        if isinstance(val, list):
            return val
        for alias in _COLLECTION_ALIASES.get(key, ()):
            val = data.get(alias)
            if isinstance(val, list):
                return val
    return []


def _get_field(row, field):
    """从一条集合记录取字段：文档名 -> 别名 -> 大小写不敏感兜底。"""
    if not isinstance(row, dict):
        return None
    if field in row:
        return row[field]
    for alias in _FIELD_ALIASES.get(field, ()):
        if alias in row:
            return row[alias]
    low = field.lower()
    for k, v in row.items():
        if isinstance(k, str) and k.lower() == low:
            return v
    return None


def _parse_dt(value):
    """解析到货日期：Java 格式 / ISO 格式；空值 -> NaT。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NaT
    if isinstance(value, pd.Timestamp):
        return value
    s = str(value).strip()
    if not s:
        return pd.NaT
    m = _JAVA_DT_RE.match(s)
    if m:
        return pd.to_datetime(f"{m.group(1)} {m.group(2)}",
                              format='%b %d %H:%M:%S %Y')
    return pd.to_datetime(s, errors='coerce')


def _to_str(value):
    """字符串字段：null / 空串归一为 NaN，其余原样字符串（保留前导 0）。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return np.nan
    s = str(value).strip()
    return np.nan if s == '' else s


def _to_int(value):
    """ID 字段转 int；无法转换 -> NaN。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return np.nan
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return np.nan


def _to_num(value):
    """数值字段原样保留（不换算、不转字符串）；无法转换 -> NaN。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return np.nan
    if isinstance(value, (int, float, np.number)):
        return value
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return np.nan


def _coerce(field: str, value):
    if field in _INT_FIELDS:
        return _to_int(value)
    if field in _NUM_FIELDS:
        return _to_num(value)
    if field in _DT_FIELDS:
        return _parse_dt(value)
    if field in _DATE_FIELDS:
        return _parse_dt(value)
    return _to_str(value)


def _build_collection_df(collection: list, cols: List[str]) -> pd.DataFrame:
    """按字段清单把一个集合原样提取为 DataFrame（空集合保列结构）。"""
    rows = [{col: _coerce(col, _get_field(item, col)) for col in cols}
            for item in collection]
    return pd.DataFrame(rows, columns=cols)


def _mapping_df(code_name: Dict[str, str],
                note: Dict[str, str] | None = None) -> pd.DataFrame:
    """码值映射字典 -> DataFrame（列：编码 / 名称 / 说明）。"""
    note = note or {}
    rows = [{'编码': code, '名称': name, '说明': note.get(code, '')}
            for code, name in code_name.items()]
    return pd.DataFrame(rows, columns=['编码', '名称', '说明'])


# ==================================================================
# 统一提取入口
# ==================================================================

def extract_request(payload) -> Dict[str, pd.DataFrame]:
    """接口请求 JSON -> 全部 DataFrame（请求数据 9 个 + 码值映射 7 个）。

    返回 dict 的 key 分两类：
    - 请求集合：接口文档 V2.0 的 9 个集合名（deviceParaList / dmdPlanDetList /
      arriveBatchList / detectSchList / qualifiedStockList / unqualifiedStockList /
      scheduleTimeList / scheduleConfigList / nonDmdAimEquipCodeCfgList）
    - 码值映射：系统字典视图名（VW_DETECT_EQUIP_TYPE / VW_DEVICE_TYPE /
      VW_YES_NO_FLAG / VW_EQUIP_CLS / VW_EQUIP_CATEG / VW_DETECT_TYPE /
      VW_DMD_PLAN_TYPE），列：编码 / 名称 / 说明

    payload 为空或非 dict 时按空请求处理（各集合空表 + 完整码值映射表）。
    """
    data = payload if isinstance(payload, dict) else {}

    result: Dict[str, pd.DataFrame] = {
        key: _build_collection_df(_get_collection(data, key), cols)
        for key, cols in _COLLECTION_COLS.items()
    }
    for view, code_name in _DICT_VIEWS.items():
        note = _DETECT_EQUIP_TYPE_NOTE if view == 'VW_DETECT_EQUIP_TYPE' else None
        result[view] = _mapping_df(code_name, note)
    return result
