# -*- coding: utf-8 -*-
"""
导出 0812 报文接口数据 + 码值映射字典 为 Excel（供算法据此计算）。
=============================================================
**独立运行**：本脚本不依赖项目任何其他模块，所有字段清单 / 码值映射 /
类型转换逻辑均内嵌；源报文默认读取同目录 `智能排程报文0812.json`。

运行方式（任意目录均可）：
    python 导出脚本_0812.py                 # 用同目录 智能排程报文0812.json
    python 导出脚本_0812.py <json路径>       # 或指定报文文件

产物（与脚本同目录）：
  - 智能排程报文0812接口数据.xlsx  9 个请求集合，字段用接口文档 V2.0 名称
  - 码值映射字典.xlsx              7 个系统字典视图（编码/名称/说明）

说明：
- 0812 报文为两份相同 JSON 拼接（json.load 报 Extra data），按第一份导出，
  与第二份逐字节一致，取哪份结果相同。
- 第 9 集合在 0812 中名为 nonDmdTargetEquipCodeCfgList（文档名
  nonDmdAimEquipCodeCfgList / 0807 名 nonDmdTargetEquipCodeCfgVOList），
  按实际出现的集合名取数，保证数据不丢（见 检定数据记录文档.md 问题 #9/#10）。
- 只做"提取"，不做翻译/推断；码值映射字典为接口文档系统字典视图原样导出。
"""
import json
import sys
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_PAYLOAD = SCRIPT_DIR / '智能排程报文0812.json'


# ==================================================================
# 请求集合字段清单（接口文档 V2.0）
# ==================================================================
COLLECTION_COLS = {
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
COLLECTION_ORDER = list(COLLECTION_COLS.keys())

# 第 9 集合出现过的所有名字（文档 / 0807 / 0812）
NONDMD_KEYS = ('nonDmdTargetEquipCodeCfgList',      # 0812 实际名
               'nonDmdTargetEquipCodeCfgVOList',    # 0807 实际名
               'nonDmdAimEquipCodeCfgList')         # 接口文档 V2.0 名


# ==================================================================
# 码值映射字典（接口文档「二、系统字典视图」）
# ==================================================================

# VW_DETECT_EQUIP_TYPE：所检设备表类型 编码 → 名称（含说明列）
DETECT_EQUIP_TYPE_DICT = {
    '01': '单相电能表', '02': '三相直接表', '03': '三相互感表',
    '04': '10kV电压互感器', '05': '20kV电压互感器',
    '06': '10kV电流互感器', '07': '20kV电流互感器',
    '08': '普通型低压电流互感器', '09': '大变比型低压电流互感器',
    '10': 'DBI型低压电流互感器', '11': '经互感器接入集中器',
    '12': '经互感器接入负荷管理终端', '13': '经互感器接入配变监测计量终端',
    '14': '经互感器接入智能量测终端', '15': '直接接入集中器',
    '16': '直接接入负荷管理终端', '17': '直接接入配变监测计量终端',
    '18': '直接接入智能量测终端',
}
DETECT_EQUIP_TYPE_NOTE = {
    '01': '', '02': '直接接入三相电能表', '03': '互感器接入三相电能表',
    '04': '', '05': '', '06': '', '07': '',
    '08': 'TA变比≤2000A', '09': 'TA变比＞2000A', '10': '抗直流型',
    '11': '', '12': '', '13': '', '14': '', '15': '', '16': '', '17': '', '18': '',
}
# VW_DEVICE_TYPE：检定仓类型 编码 → 名称
DEVICE_TYPE_DICT = {
    '01': '单相电能表检定仓', '02': '单三相兼容检定仓', '03': '终端检定仓',
    '04': '三相电能表检定仓', '05': '三相表兼容终端检定仓',
    '06': '10kv/20kv电压兼容仓', '07': '10kv/20kv电流兼容仓',
    '08': '普通/大变比低压CT兼容仓', '09': '普通/DBI低压CT兼容仓',
}
# VW_YES_NO_FLAG：是否标志
YES_NO_FLAG_DICT = {'0': '否', '1': '是'}
# VW_EQUIP_CLS：设备分类（V2.0 新增）
EQUIP_CLS_DICT = {
    '01': '单相电能表', '02': '三相电能表', '03': '负荷管理终端',
    '04': '集中器', '05': '配变监测计量终端', '06': '10kV电流互感器',
    '07': '10kV电压互感器', '08': '低压电流互感器', '09': '组合互感器',
    '10': '厂站终端', '11': '通信模块', '19': '智能量测终端',
    '20': '20kV电流互感器', '21': '20kV电压互感器', '23': '周转箱',
    '24': '栈板', '31': '单相计量表箱', '32': '10kV低压计量表箱',
    '33': '三相计量表箱', '34': '10kV高压计量表箱',
    '35': '单相费控计量表箱', '36': '三相费控计量表箱', '37': '集中器箱',
    '41': '运行封印', '42': '端子盖',
}
# VW_EQUIP_CATEG：设备类别（V2.0 新增）
EQUIP_CATEG_DICT = {
    '01': '电能表', '02': '互感器', '09': '计量自动化终端', '10': '计量表箱',
    '15': '通信模块', '17': '封印', '18': '开关', '19': '周转箱',
    '21': '配件', '78': '栈板',
}
# VW_DETECT_TYPE：检定类别（V2.0 新增）
DETECT_TYPE_DICT = {
    '01': '全性能试验', '02': '到货后抽样检测', '03': '首次检定',
    '04': '不合格设备复检', '05': '流水线适应性检查', '07': '库存复检',
    '11': '临时检定-委托', '12': '临时检定-厂返退还',
    '13': '计量标准设备检定/校准', '14': '运行抽检',
    '20': '到货后全性能试验', '21': '样品比对', '22': '解密',
    '50': '期间核查', '51': '重复性试验', '52': '稳定性考核',
    '53': '量值溯源', '54': '测试设备监测/校准', '55': '分拣鉴定',
}
# VW_DMD_PLAN_TYPE：计划类型（V2.0 新增）
DMD_PLAN_TYPE_DICT = {'01': '月计划', '02': '紧急计划'}

VIEW_ORDER = [
    'VW_DETECT_EQUIP_TYPE', 'VW_DEVICE_TYPE', 'VW_YES_NO_FLAG',
    'VW_EQUIP_CLS', 'VW_EQUIP_CATEG', 'VW_DETECT_TYPE', 'VW_DMD_PLAN_TYPE',
]
_DICT_VIEWS = {
    'VW_DETECT_EQUIP_TYPE': (DETECT_EQUIP_TYPE_DICT, DETECT_EQUIP_TYPE_NOTE),
    'VW_DEVICE_TYPE': (DEVICE_TYPE_DICT, None),
    'VW_YES_NO_FLAG': (YES_NO_FLAG_DICT, None),
    'VW_EQUIP_CLS': (EQUIP_CLS_DICT, None),
    'VW_EQUIP_CATEG': (EQUIP_CATEG_DICT, None),
    'VW_DETECT_TYPE': (DETECT_TYPE_DICT, None),
    'VW_DMD_PLAN_TYPE': (DMD_PLAN_TYPE_DICT, None),
}


# ==================================================================
# 字段类型归类与转换（只做类型适配，不做业务翻译/推断）
# ==================================================================
_INT_FIELDS = {'dmdPlanDetId', 'detectSchemeId'}
_NUM_FIELDS = {'posNum', 'sumQty', 'arriveQty', 'lowerLimitQty',
               'qualifiedQty', 'distLockQty', 'detectUQty',
               'timeInterval', 'overtime', 'allocationRatio'}
_DT_FIELDS = {'arriveDate', 'workDay'}
# 其余字段一律按字符串提取（保留前导 0）：sysNo / deviceNo / equipCode /
# equipCls / equipCateg / detectEquipType / deviceType / planType / detectType /
# aimEquipCode / pEquipCode / sysName / equipDesc / startTime / endTime / schTime 等

# Java Date.toString 格式：Wed Aug 05 00:00:00 CST 2026
_JAVA_DT_RE = __import__('re').compile(
    r'^[A-Za-z]{3}\s+([A-Za-z]{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+'
    r'[A-Za-z]{2,5}\s+(\d{4})$')


def _parse_dt(value):
    """解析日期：Java 格式 / ISO 格式；空值 -> NaT。"""
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
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NA
    s = str(value).strip()
    return pd.NA if s == '' else s


def _to_int(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NA
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return pd.NA


def _to_num(value):
    """数值原样保留（不换算）；无法转换 -> NA。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NA
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return pd.NA


def _coerce(field, value):
    if field in _INT_FIELDS:
        return _to_int(value)
    if field in _NUM_FIELDS:
        return _to_num(value)
    if field in _DT_FIELDS:
        return _parse_dt(value)
    return _to_str(value)


def _get_field(row, field):
    """字段取值：文档名 -> 别名 -> 大小写不敏感兜底。"""
    if not isinstance(row, dict):
        return None
    if field in row:
        return row[field]
    if field == 'allocationRatio' and 'allocationRation' in row:  # 报文拼写别名
        return row['allocationRation']
    if field == 'pEquipCode' and 'pequipCode' in row:            # 报文大小写别名
        return row['pequipCode']
    low = field.lower()
    for k, v in row.items():
        if isinstance(k, str) and k.lower() == low:
            return v
    return None


def _build_collection_df(collection, cols):
    rows = [{col: _coerce(col, _get_field(item, col)) for col in cols}
            for item in collection]
    return pd.DataFrame(rows, columns=cols)


def _mapping_df(code_name, note):
    note = note or {}
    rows = [{'编码': code, '名称': name, '说明': note.get(code, '')}
            for code, name in code_name.items()]
    return pd.DataFrame(rows, columns=['编码', '名称', '说明'])


# ==================================================================
# 报文读取
# ==================================================================

def load_payload(path):
    """0812 是两份相同报文拼接，取第一份。"""
    raw = Path(path).read_text(encoding='utf-8')
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(raw)
        return obj
    return data[0] if isinstance(data, list) else data


def get_collection(payload, key):
    """按字段清单取集合；空/缺失返回空列表。"""
    if not isinstance(payload, dict):
        return []
    val = payload.get(key)
    if isinstance(val, list):
        return val
    if key == 'nonDmdAimEquipCodeCfgList':  # 第 9 集合按实际名兜底
        for alias in NONDMD_KEYS:
            val = payload.get(alias)
            if isinstance(val, list):
                return val
    return []


def main():
    payload_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PAYLOAD
    if not Path(payload_path).exists():
        print(f"[错误] 找不到报文文件: {payload_path}")
        sys.exit(1)

    payload = load_payload(payload_path)
    print(f"报文: {Path(payload_path).resolve()}（第一份）")

    out_collections = SCRIPT_DIR / '智能排程报文0812接口数据.xlsx'
    with pd.ExcelWriter(out_collections, engine='openpyxl') as writer:
        for key in COLLECTION_ORDER:
            rows = get_collection(payload, key)
            df = _build_collection_df(rows, COLLECTION_COLS[key])
            df.to_excel(writer, sheet_name=key, index=False)
            print(f"  {key:<34} {len(df)} 行 x {df.shape[1]} 列")

    out_mappings = SCRIPT_DIR / '码值映射字典.xlsx'
    with pd.ExcelWriter(out_mappings, engine='openpyxl') as writer:
        for key in VIEW_ORDER:
            code_name, note = _DICT_VIEWS[key]
            df = _mapping_df(code_name, note)
            df.to_excel(writer, sheet_name=key, index=False)
            print(f"  {key:<26} {len(df)} 条")

    print(f"已导出 -> {out_collections.name} / {out_mappings.name}")


if __name__ == '__main__':
    main()
