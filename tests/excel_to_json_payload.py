# -*- coding: utf-8 -*-
"""
Excel → 接口 JSON 测试报文生成工具
==================================
把「检定仓情况-20260825.xlsx」按接口文档 v0.0.6 转换为 9 个 JSON 集合，
供 HTTP 接口测试用（与 CLI 兑底读取同一份 Excel，两条路径结果可对照）。

用法（项目根目录）：
    PYTHONIOENCODING=utf-8 python -X utf8 tests/excel_to_json_payload.py

输出：docs/报文/0825_检定仓情况_转json.json（单个合法请求体）

转换原则：Excel 里的中文（设备分类/所检设备表类型/检定仓类型/接入方式/是否已抽检）
全部转成接口契约定义的编码；空值按接口必填字段补齐默认。
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.detect.constants import (  # noqa: E402
    CAT_NAME_TO_DETECT_CODE,
    CAT_NAME_TO_EQUIP_CLS_CODE,
    DETECT_EQUIP_TYPE_MAP,
)
from modules.detect.category import get_equip_categ_code, parse_device_category  # noqa: E402

SRC = Path(r'D:/WYJ/库存优化与检定排程/深圳项目/docs/样例/检定仓情况-20260825.xlsx')
DST = Path(r'D:/WYJ/库存优化与检定排程/深圳项目/docs/报文/0825_检定仓情况_转json.json')

DETECT_EQUIP_TYPE_NAME_TO_CODE = {v: k for k, v in DETECT_EQUIP_TYPE_MAP.items()}


def equip_type_code(name):
    """所检设备表类型 中文名 → VW_DETECT_EQUIP_TYPE 编码（'01'-'18'）。

    先按 VW_DETECT_EQUIP_TYPE 名称精确反查；查不到（§2-C 已知项：负荷控制终端/
    配变监测终端等不在字典里的名称）按算法同款关键词分类器兜底——终端类就近映射到
    可往返的码（经互感→14、直接→15），保证 JSON 路径与 Excel 路径（算法直接解析中文）
    得到相同的分类码与接入方式码。
    """
    if name is None or pd.isna(name):
        return None
    s = str(name).strip().replace('\n', ' ')
    code = DETECT_EQUIP_TYPE_NAME_TO_CODE.get(s)
    if code is not None:
        return code
    cat = parse_device_category(s)
    if cat == 14:
        return '15' if '直接' in s else '14'
    return f"{cat:02d}" if isinstance(cat, int) else None


def detect_equip_type_for_spec(equip_code, fallback_name=None):
    """到货批次 detectEquipType：优先按规格设备码信息表的权威 设备分类+接入方式 推导
    （与 Excel 路径的分类一致），spec 无此码时用所检设备表类型名称兜底。

    终端类按接入方式选码（经互感→14、直接→15）；非终端分类的接入方式不影响算法
    （接入方式只在终端仓规则使用）。接入方式为空时返回 ''（两条路径同为空→未知）。
    """
    cat = spec_cat_map.get(equip_code)
    if cat and pd.notna(cat):
        dcode = CAT_NAME_TO_DETECT_CODE.get(cat)
        if dcode == 14:
            acc = str(spec_access_map.get(equip_code, '') or '')
            if '直接' in acc:
                return '15'
            if '经互感' in acc:
                return '14'
            return ''  # 接入方式为空 → 保持未知（与 Excel 路径一致）
        return f"{dcode:02d}" if dcode else ''
    return equip_type_code(fallback_name) or ''


def equip_cls_code(cat_name):
    """设备分类 中文名 → VW_EQUIP_CLS 编码（'01' 零填充）。"""
    if cat_name is None or pd.isna(cat_name):
        return ''
    code = CAT_NAME_TO_EQUIP_CLS_CODE.get(str(cat_name).strip())
    return f"{code:02d}" if code else ''


def equip_categ_code(cat_name):
    """设备分类 中文名 → VW_EQUIP_CATEG 编码。"""
    if cat_name is None or pd.isna(cat_name):
        return ''
    code = get_equip_categ_code(str(cat_name).strip())
    return f"{code:02d}" if code else ''


def sample_flag(val):
    """是否已抽检 是/否 → 接口编码 '1'/'0'（空值默认已抽检）。"""
    if val is None or pd.isna(val):
        return '1'
    return '1' if str(val).strip() == '是' else '0'


def to_int(val, default=0):
    if val is None or pd.isna(val):
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def fmt_dt(val):
    """时间 → 'yyyy-MM-dd HH:mm:ss'；空值 → ''。"""
    if val is None or pd.isna(val):
        return ''
    return pd.Timestamp(val).strftime('%Y-%m-%d %H:%M:%S')


def fmt_date(val):
    if val is None or pd.isna(val):
        return ''
    return pd.Timestamp(val).strftime('%Y-%m-%d')


def fmt_time(val):
    """'HH:MM:SS' / 'HH:MM' → 'HH:MM'。"""
    if val is None or pd.isna(val):
        return '09:00'
    s = str(val).strip()
    if s and ' ' in s:
        s = s.split(' ')[1]
    if len(s.split(':')) >= 3:
        s = ':'.join(s.split(':')[:2])
    return s or '09:00'


# 接口文档 v0.0.6 各集合字段（参数英文名）：必填字段 + 全部合法字段
SPEC_FIELDS = {
    'deviceParaList': ({'sysNo', 'sysName', 'deviceType', 'deviceNo', 'deviceName', 'detectEquipType', 'posNum'}, set()),
    'dmdPlanDetList': ({'dmdPlanDetId', 'dmdPlanNo', 'planType', 'planYear', 'planMonth', 'appOrg',
                        'equipCateg', 'equipCls', 'equipCode', 'equipDesc', 'pEquipCode', 'sumQty'},
                       {'detectEquipType'}),  # v0.0.6 已删除该字段（V0.0.2 删需求明细所检设备表类型）
    'arriveBatchList': ({'arriveBatchNo', 'equipCateg', 'equipCls', 'equipCode', 'equipDesc',
                         'arriveQty', 'arriveDate', 'detectEquipType', 'sampleFlag', 'sampleQty'}, set()),
    'detectSchList': ({'equipCode', 'detectType', 'detectSchemeId', 'schTime'}, set()),
    'qualifiedStockList': ({'equipCode', 'lowerLimitQty', 'qualifiedQty', 'distLockQty'}, set()),
    'unqualifiedStockList': ({'equipCode', 'arriveBatchNo', 'detectUQty', 'sampleFlag', 'sampleQty'}, set()),
    'scheduleTimeList': ({'workDay', 'startTime', 'endTime'}, set()),
    'scheduleConfigList': ({'sysNo', 'sysName', 'timeInterval', 'overtime'}, set()),
    'nonDmdTargetEquipCodeCfgList': ({'equipCode', 'aimEquipCode', 'allocationRatio'}, set()),
}


def validate_payload(payload):
    """按接口文档 v0.0.6 校验各集合字段：必填齐全、无多余字段；返回问题清单。"""
    problems = []
    for key, (required, _optional) in SPEC_FIELDS.items():
        rows = payload.get(key) or []
        if not isinstance(rows, list):
            problems.append(f"{key} 不是数组")
            continue
        for i, r in enumerate(rows):
            keys = set(r.keys())
            missing = required - keys
            if missing:
                problems.append(f"{key}[{i}] 缺必填字段: {sorted(missing)}")
            extra = keys - required - _optional
            if extra:
                problems.append(f"{key}[{i}] 多余字段: {sorted(extra)}")
    return problems


def build():
    df_overall = pd.read_excel(SRC, sheet_name='整体情况')
    df_arrival = pd.read_excel(SRC, sheet_name='到货排程-到货计划旧表', converters={'设备规格': str})
    df_demand = pd.read_excel(SRC, sheet_name='需求明细', converters={'设备类型码大码': str, '设备码': str})
    df_spec = pd.read_excel(SRC, sheet_name='规格设备码信息表', converters={'设备码': str})
    df_qualified = pd.read_excel(SRC, sheet_name='合格品库存信息表', converters={'设备码': str})
    df_unqualified = pd.read_excel(SRC, sheet_name='非合格品库存', converters={'设备类型码': str})
    df_time = pd.read_excel(SRC, sheet_name='排程时间配置')
    df_gap = pd.read_excel(SRC, sheet_name='调度时间间隔配置')
    df_ndm = pd.read_excel(SRC, sheet_name='非需求设备目标设备类型配置',
                           converters={'设备类型码大码': str, '目标设备类型码': str})

    # 检定仓配置表 = 仓类型ID 的权威来源（与算法 Excel 路径 chamber_type_id_map 同源），
    # deviceParaList.deviceType 直接带 仓类型ID，避免整体情况里中文仓类型名称的口径问题
    df_cc = pd.read_excel(SRC, sheet_name='检定仓配置表')
    df_cc.columns = [str(c).strip() for c in df_cc.columns]
    chamber_type_id_by_key = {
        (int(r['检定线ID']), str(r['检定仓编号']).strip()): int(r['仓类型ID'])
        for _, r in df_cc.iterrows()
    }

    # 规格设备码信息表 = 设备分类/接入方式的权威来源（与算法 Excel 路径一致）
    global spec_cat_map, spec_access_map
    spec_cat_map = dict(zip(df_spec['设备码'].astype(str).str.strip(),
                            df_spec['设备分类'].astype(str)))
    spec_access_map = dict(zip(df_spec['设备码'].astype(str).str.strip(),
                               df_spec['接入方式'].astype(str)))

    payload = {}

    # 1. deviceParaList ← 整体情况（合并单元格行 ffill，与算法 prepare 一致；
    #    deviceType = 检定仓配置表的 仓类型ID）
    ov = df_overall[['线体编号', '线体名称', '检定仓编号']].ffill()
    ov = pd.concat([ov, df_overall[['所检设备表类型', '表位数']]], axis=1)
    rows = []
    for _, r in ov.iterrows():
        if pd.isna(r['检定仓编号']):
            continue
        key = (int(r['线体编号']), str(r['检定仓编号']).strip())
        type_id = chamber_type_id_by_key.get(key)
        etc = equip_type_code(r['所检设备表类型'])
        if type_id is None or etc is None:
            print(f"  [警告] 整体情况行 线体={r['线体编号']} 仓={r['检定仓编号']} "
                  f"仓类型ID={type_id} / 所检类型「{r['所检设备表类型']}」无码值映射，跳过")
            continue
        rows.append({
            'sysNo': str(key[0]),
            'sysName': str(r['线体名称']).strip(),
            'deviceType': f"{type_id:02d}",
            'deviceNo': key[1],
            'deviceName': key[1],
            'detectEquipType': etc,
            'posNum': to_int(r['表位数']),
        })
    payload['deviceParaList'] = rows

    # 2. scheduleConfigList ← 调度时间间隔配置
    rows = []
    for _, r in df_gap.iterrows():
        rows.append({
            'sysNo': str(int(r['线体编号'])),
            'sysName': str(r['线体名称']).strip() if pd.notna(r['线体名称']) else '',
            'timeInterval': to_int(r['调度时间间隔（秒）'], 300),
            'overtime': to_int(r['允许加班时长（小时）'], 0),
        })
    payload['scheduleConfigList'] = rows

    # 3. arriveBatchList ← 到货排程-到货计划旧表
    spec_desc = dict(zip(df_spec['设备码'].astype(str).str.strip(),
                         df_spec['设备码描述'].astype(str) if '设备码描述' in df_spec.columns else ''))
    rows = []
    for _, r in df_arrival.iterrows():
        if pd.isna(r['到货批次号']):
            continue
        equip_code = str(r['设备规格']).strip()
        rows.append({
            'arriveBatchNo': str(r['到货批次号']).strip(),
            'equipCateg': equip_categ_code(r['设备分类']),
            'equipCls': equip_cls_code(r['设备分类']),
            'equipCode': equip_code,
            'equipDesc': spec_desc.get(equip_code, ''),
            'arriveQty': to_int(r['数量']),
            'arriveDate': fmt_dt(r['预计到货日期']),
            # 按规格表权威 设备分类+接入方式 推导（与 Excel 路径分类一致）
            'detectEquipType': detect_equip_type_for_spec(equip_code, r['所检设备表类型']),
            'sampleFlag': sample_flag(r['是否已抽检']),
            'sampleQty': to_int(r['抽检数量']),
        })
    payload['arriveBatchList'] = rows

    # 4. dmdPlanDetList ← 需求明细
    rows = []
    for i, r in df_demand.iterrows():
        month = str(r['所属月份']).strip()
        rows.append({
            'dmdPlanDetId': i + 1,
            'dmdPlanNo': '',
            'planType': '01',
            'planYear': month[:4],
            'planMonth': month[4:6],
            'appOrg': '',
            'equipCateg': equip_categ_code(r['设备分类']),
            'equipCls': equip_cls_code(r['设备分类']),
            'equipCode': str(r['设备码']).strip(),
            'equipDesc': str(r['设备码描述']).strip() if pd.notna(r['设备码描述']) else '',
            'pEquipCode': str(r['设备类型码大码']).strip(),
            'sumQty': to_int(r['申请数量']),
        })
    payload['dmdPlanDetList'] = rows

    # 5. detectSchList ← 规格设备码信息表
    rows = []
    for _, r in df_spec.iterrows():
        rows.append({
            'equipCode': str(r['设备码']).strip(),
            'detectType': f"{to_int(r['检定类别码值'], 3):02d}",
            'detectSchemeId': to_int(r['参数标识'], 0) or None,
            'schTime': to_int(r['自动检定时间'], 0),
        })
    payload['detectSchList'] = rows

    # 6. qualifiedStockList ← 合格品库存信息表
    rows = []
    for _, r in df_qualified.iterrows():
        rows.append({
            'equipCode': str(r['设备码']).strip(),
            'lowerLimitQty': to_int(r['安全库存']),
            'qualifiedQty': to_int(r['合格品库存']),
            'distLockQty': to_int(r['未配送库存']),
        })
    payload['qualifiedStockList'] = rows

    # 7. unqualifiedStockList ← 非合格品库存
    rows = []
    for _, r in df_unqualified.iterrows():
        rows.append({
            'equipCode': str(r['设备类型码']).strip(),
            'arriveBatchNo': str(r['到货批次号']).strip() if pd.notna(r['到货批次号']) else '',
            'detectUQty': to_int(r['可检库存']),
            'sampleFlag': sample_flag(r['是否已抽检']),
            'sampleQty': to_int(r['抽检数量']),
        })
    payload['unqualifiedStockList'] = rows

    # 8. scheduleTimeList ← 排程时间配置
    rows = []
    for _, r in df_time.iterrows():
        rows.append({
            'workDay': fmt_date(r['工作日日期']),
            'startTime': fmt_time(r['开始时间']),
            'endTime': fmt_time(r['结束时间']),
        })
    payload['scheduleTimeList'] = rows

    # 9. nonDmdTargetEquipCodeCfgList ← 非需求设备目标设备类型配置
    rows = []
    for _, r in df_ndm.iterrows():
        rows.append({
            'equipCode': str(r['设备类型码大码']).strip(),
            'aimEquipCode': str(r['目标设备类型码']).strip(),
            'allocationRatio': float(r['分配比例（%）']),
        })
    payload['nonDmdTargetEquipCodeCfgList'] = rows

    return payload


if __name__ == '__main__':
    payload = build()
    problems = validate_payload(payload)
    if problems:
        print("接口规范校验发现问题:")
        for p in problems:
            print(f"  ! {p}")
    else:
        print("接口规范校验: 全部字段符合 v0.0.6 ✓")
    DST.parent.mkdir(parents=True, exist_ok=True)
    with open(DST, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"已生成: {DST}")
    for k, v in payload.items():
        print(f"  {k}: {len(v)} 条")
