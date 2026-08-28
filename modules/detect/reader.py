"""
检定模块 — 数据读取适配
========================
把两种输入格式统一适配成算法期望的 12 个 DataFrame（8.11/8.16 输入模型）：
- read_excel : 读取 Excel 文件（离线兑底 / 开发验证）
- read_json  : 解析接口文档（接口说明v2.0）定义的 9 个 JSON 入参集合（生产环境）

不做多余封装，只做格式适配 + 异常处理。两种实现返回**同构**的
{key: DataFrame} —— key 与列名均与 prepare.process_data() 期望一致，
因此核心算法对两条路径完全复用。

8.11/8.16 数据层补全（相对 8.03 数据层）：
- 新增第 12 sheet「非需求设备目标设备类型配置」（non_demand_target）
- demand 增列 设备码 / 设备分类；arrival / unqualified 的设备分类做 equipCls 码→名转换
- spec 增列 设备码描述；设备分类优先按 detectEquipType 推断、equipCls 码→名兜底
  （0812 场景 detectEquipType 全空，靠 equipCls 编码转出分类，不再全 None）
- gap_config 增列 允许加班时长（小时）

8.17 数据层补全：
- spec 增列 参数标识（detectSchList.detectSchemeId），作为出参 detectSchemeId 的数据源

8.25 数据层补全（接口 v0.0.6）：
- arrival / unqualified 增列 是否已抽检（sampleFlag）、抽检数量（sampleQty）
- 出参新增 detectType（检定类别：02 抽样试验 / 03 首次检定）
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

import pandas as pd

from .category import parse_device_category_name
from .constants import (
    ACCESS_DIRECT,
    ACCESS_HUGAN,
    ACCESS_UNKNOWN,
    CAT_NAME_TO_DETECT_CODE,
    DETECT_EQUIP_TYPE_MAP,
    DEVICE_TYPE_MAP,
    EQUIP_CLS_MAP,
    HUGAN_ACCESS_CODES,
)

logger = logging.getLogger(__name__)


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


def _equip_cls_name(code):
    """设备分类编码 -> 名称（VW_EQUIP_CLS）；若已是名称则原样返回。

    0812 报文 equipCls 是编码（'01'/'06'/'08'/'19'…），此前原样写入导致
    算法分类匹配不上；现在统一转成中文分类名。
    """
    if code is None or pd.isna(code):
        return None
    code = str(code).strip()
    return EQUIP_CLS_MAP.get(code, code)


def _sample_flag_name(val):
    """是否已抽检（sampleFlag）归一化为 是/否。

    接口 v0.0.6 定义 0否/1是；8.28 算法只认中文 '是' 为已抽检，
    其余（'否'/'0'/空）视为未抽检（空值由 prepare 兜底为已抽检）。
    此处把接口编码统一转成 是/否，保证两条路径语义一致。
    """
    if val is None or pd.isna(val):
        return None
    s = str(val).strip()
    if s in ('1', '1.0', '是', 'True', 'true'):
        return '是'
    if s in ('0', '0.0', '否', 'False', 'false'):
        return '否'
    return s


def _infer_category(equip_type_code_or_name):
    """从所检设备表类型推断设备分类（中文名）。

    接口入参的 detectEquipType 是编码（01-18），先经 VW_DETECT_EQUIP_TYPE
    转为名称，再做与 8.16 parse_device_category 一致的关键词匹配。
    返回中文分类名（prepare 再经 CAT_NAME_TO_DETECT_CODE 转码，spec 分类不直接落码）；
    无法识别返回 None。
    """
    name = _equip_type_name(equip_type_code_or_name)
    if not name:
        return None
    return parse_device_category_name(name)


def _infer_access(equip_type_code):
    """从所检设备表类型编码推断接入方式码（ACCESS_HUGAN='1' / ACCESS_DIRECT='0'）。

    接口入参没有"接入方式"字段，编码 11-14 为经互感系列，15-18 为直接接入系列。
    8.28 起核心算法按码判断，Excel 路径的中文接入方式由 prepare 归一化为同套码。
    """
    if equip_type_code is None or pd.isna(equip_type_code):
        return ACCESS_UNKNOWN
    code = str(equip_type_code).strip()
    if code in HUGAN_ACCESS_CODES:
        return ACCESS_HUGAN
    if code in DETECT_EQUIP_TYPE_MAP:
        return ACCESS_DIRECT
    return ACCESS_UNKNOWN


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
# 8.11 脚本用 converters 强制设备码类列为字符串（避免 int/str 混用导致字典 key 不匹配）。
# 列名转换器对不含该列的 sheet 无副作用，统一加在全部 sheet 上。
_CONVERTERS = {
    '设备码': str,
    '设备规格': str,
    '设备类型码大码': str,
    '目标设备类型码': str,
    '设备类型码': str,
}


def read_excel(file_path: Path, sheet_names: Dict[str, str]) -> Dict[str, pd.DataFrame]:
    """读取 Excel 文件 12 个 sheet，返回 {key: DataFrame}。

    文件不存在抛 FileNotFoundError；缺少必需 sheet 抛 ValueError（带 sheet 名）。
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {file_path}")
    dfs = {}
    for key, sheet in sheet_names.items():
        try:
            dfs[key] = pd.read_excel(file_path, sheet_name=sheet, converters=_CONVERTERS)
            logger.debug("读取 sheet「%s」（key: %s）：%d 行", sheet, key, len(dfs[key]))
        except ValueError as e:
            raise ValueError(f"Excel 缺少必需 sheet「{sheet}」（内部 key: {key}）: {e}") from e
    logger.info("Excel 读取完成：%d 个 sheet，共 %d 行", len(dfs), sum(len(df) for df in dfs.values()))
    return dfs


# ==================================================================
# JSON 实现（接口文档入参）
# ==================================================================
# 入参集合 -> 内部 DataFrame 的对应关系：
#   deviceParaList       -> overall / line_info / chamber_type / chamber_config
#   dmdPlanDetList       -> demand / spec
#   arriveBatchList      -> arrival / spec
#   detectSchList        -> spec
#   qualifiedStockList   -> qualified
#   unqualifiedStockList -> unqualified
#   scheduleTimeList     -> time_config
#   scheduleConfigList   -> gap_config / line_info
#   nonDmdAimEquipCodeCfgList -> non_demand_target

# 每个内部 key 对应的列名（与 Excel sheet 列名一致，保证空数据也有正确结构）
_COLS = {
    'overall': ['线体编号', '线体名称', '检定仓编号', '检定仓类型', '所检设备表类型', '表位数'],
    'line_info': ['检定线ID', '检定线名称'],
    'chamber_type': ['仓类型ID', '仓类型名称'],
    'chamber_config': ['检定线ID', '检定仓编号', '仓类型ID'],
    'arrival': ['到货批次号', '设备分类', '设备规格', '数量', '预计到货日期', '是否已抽检', '抽检数量'],
    'demand': ['所属月份', '设备类型码大码', '申请数量', '设备码', '设备分类'],
    'spec': ['设备码', '设备分类', '接入方式', '自动检定时间', '设备码描述', '参数标识'],
    'qualified': ['设备码', '合格品库存', '未配送库存', '安全库存'],
    'unqualified': ['到货批次号', '设备类型码', '设备分类', '可检库存', '是否已抽检', '抽检数量'],
    'time_config': ['工作日日期', '开始时间', '结束时间'],
    'gap_config': ['线体编号', '调度时间间隔（秒）', '允许加班时长（小时）'],
    'non_demand_target': ['设备类型码大码', '目标设备类型码', '分配比例（%）'],
}

# 第 9 集合「非需求设备目标设备类型配置」出现过的所有名字
# （接口文档 V2.0 / 0807 报文 / 0812 报文，按出现频次排列）
_NON_DMD_KEYS = (
    'nonDmdTargetEquipCodeCfgList',      # 0812 实际名
    'nonDmdTargetEquipCodeCfgVOList',    # 0807 实际名
    'nonDmdAimEquipCodeCfgList',         # 接口文档 V2.0 名
)


def _get(data: dict, key: str) -> list:
    return data.get(key) or []


def _get_non_demand_target(data: dict) -> list:
    """取第 9 集合：按实际出现的集合名兜底取数，保证数据不丢。"""
    if not isinstance(data, dict):
        return []
    for key in _NON_DMD_KEYS:
        val = data.get(key)
        if isinstance(val, list):
            return val
    return []


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
            '设备分类': _equip_cls_name(r.get('equipCls')),
            '设备规格': r.get('equipCode'),
            '数量': r.get('arriveQty'),
            '预计到货日期': _parse_dt(r.get('arriveDate')),
            '是否已抽检': _sample_flag_name(r.get('sampleFlag')),  # 0否/1是 → 是/否（v0.0.6）
            '抽检数量': r.get('sampleQty'),
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
            # 需求按"设备类型码大码"聚合；缺省时回退到设备类型码（0812 pEquipCode==equipCode）
            '设备类型码大码': r.get('pEquipCode') or r.get('equipCode'),
            '申请数量': r.get('sumQty'),
            '设备码': r.get('equipCode'),
            '设备分类': _equip_cls_name(r.get('equipCls')),
        })
    return _frame('demand', rows)


def _build_spec(data) -> pd.DataFrame:
    """规格设备码信息表：由 detectSchList + 需求/到货 跨集合聚合合成。

    - 设备码 / 自动检定时间  <- detectSchList (equipCode / schTime)
    - 设备分类              <- 优先按 detectEquipType 推断（枚举有文档、能推出算法
                               认可的中文分类名）；推断不出时用 equipCls 码→名兜底
                               （0812 场景 detectEquipType 全空，靠 equipCls 编码转出）
    - 接入方式              <- 由 detectEquipType 编码推断（接口无此字段）
    - 设备码描述            <- 需求/到货的 equipDesc（8.11 用它区分低压CT 子类型）
    - 参数标识              <- detectSchList 的 detectSchemeId（8.17 出参 detectSchemeId 的数据源）
    """
    cls_map, etype_map, desc_map = {}, {}, {}
    for r in list(_get(data, 'dmdPlanDetList')) + list(_get(data, 'arriveBatchList')):
        code = r.get('equipCode')
        if code is None or pd.isna(code):
            continue
        code = str(code).strip()
        if r.get('equipCls') is not None and pd.notna(r.get('equipCls')):
            cls_map[code] = str(r['equipCls']).strip()
        if r.get('detectEquipType') is not None:
            etype_map[code] = str(r['detectEquipType']).strip()
        if r.get('equipDesc') is not None and pd.notna(r.get('equipDesc')):
            desc_map[code] = str(r['equipDesc']).strip()

    sch_time = {}
    sch_scheme = {}
    for r in _get(data, 'detectSchList'):
        code = r.get('equipCode')
        if code is None or pd.isna(code):
            continue
        code = str(code).strip()
        if r.get('schTime') is not None and pd.notna(r.get('schTime')):
            sch_time[code] = int(r['schTime'])
        if r.get('detectSchemeId') is not None and pd.notna(r.get('detectSchemeId')):
            sch_scheme[code] = int(r['detectSchemeId'])

    rows = []
    for code in sorted(set(cls_map) | set(etype_map) | set(sch_time) | set(sch_scheme)):
        etype = etype_map.get(code)
        cat = _infer_category(etype)
        if cat:
            logger.debug("设备码 %s：按 detectEquipType=%s 推断设备分类「%s」", code, etype, cat)
        else:
            raw_cls = cls_map.get(code)
            cat = _equip_cls_name(raw_cls)
            if cat and CAT_NAME_TO_DETECT_CODE.get(cat) is not None:
                # equipCls 兜底出的名称能被算法分类体系识别（已是中文名，或码→名转换成功）
                logger.debug("设备码 %s：detectEquipType 无法识别，按 equipCls=%s 兜底分类「%s」",
                             code, raw_cls, cat)
            elif cat:
                logger.warning("设备码 %s 无法推断设备分类：detectEquipType=%s 无法识别，"
                               "equipCls=%s 兜底为「%s」但不被算法分类体系识别"
                               "（该设备码将无法排程）", code, etype, raw_cls, cat)
            else:
                logger.warning("设备码 %s 无法推断设备分类：缺 detectEquipType 且缺 equipCls"
                               "（该设备码将无法排程）", code)
        rows.append({
            '设备码': code,
            '设备分类': cat,
            '接入方式': _infer_access(etype),
            '自动检定时间': sch_time.get(code),
            '设备码描述': desc_map.get(code),
            '参数标识': sch_scheme.get(code),
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
            '设备分类': _equip_cls_name(r.get('equipCls')),
            '可检库存': r.get('detectUQty'),
            '是否已抽检': _sample_flag_name(r.get('sampleFlag')),  # 0否/1是 → 是/否（v0.0.6）
            '抽检数量': r.get('sampleQty'),
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
            '允许加班时长（小时）': r.get('overtime'),
        })
    return _frame('gap_config', rows)


def _build_non_demand_target(data) -> pd.DataFrame:
    rows = []
    for r in _get_non_demand_target(data):
        rows.append({
            '设备类型码大码': r.get('equipCode'),
            '目标设备类型码': r.get('aimEquipCode'),
            '分配比例（%）': r.get('allocationRatio'),
        })
    return _frame('non_demand_target', rows)


def read_json(json_data: dict) -> Dict[str, pd.DataFrame]:
    """解析接口文档 9 个 JSON 入参集合，转换为与 Excel 同列的 12 个 DataFrame。

    json_data 为空或非 dict 时抛 ValueError（服务层已把空请求体挡在路由外，
    此处兜底防御）。
    """
    if json_data is None:
        json_data = {}
    if not isinstance(json_data, dict):
        raise ValueError(f"入参必须是 JSON 对象，实际类型: {type(json_data).__name__}")

    result = {
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
        'non_demand_target': _build_non_demand_target(json_data),
    }
    for key, df in result.items():
        logger.debug("接口集合解析 [%s]：%d 行", key, len(df))
    return result
