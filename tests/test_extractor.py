# -*- coding: utf-8 -*-
"""
接口数据提取器（data/extractor.py）测试。
==========================================
运行方式（在项目根目录）：
    python tests/test_extractor.py

覆盖：
- 请求集合 9 个 + 码值映射 7 个，shape 正确
- 设备码 / sysNo 前导 0 保留为字符串
- Java 日期格式解析、空串归一 NaN、时间未补零原样保留
- 非需求集合双别名、allocationRation 字段别名
- 空集合保列结构；空请求体仍返回完整码值映射
"""
import json
import sys
from pathlib import Path

import pandas as pd

# 把项目根目录加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.detect.extractor import extract_request  # noqa: E402

PAYLOAD_PATH = Path(__file__).resolve().parent.parent / 'docs' / '报文' / '智能排程报文0807.json'

# 请求集合名（接口文档 V2.0）与期望 shape
_EXPECTED_COLLECTIONS = {
    'deviceParaList': (122, 7),
    'dmdPlanDetList': (4, 12),
    'arriveBatchList': (15, 8),
    'detectSchList': (28, 4),
    'qualifiedStockList': (86, 4),
    'unqualifiedStockList': (0, 3),
    'scheduleTimeList': (25, 3),
    'scheduleConfigList': (4, 4),
    'nonDmdAimEquipCodeCfgList': (8, 3),
}

# 码值映射视图名（接口文档 V2.0 系统字典视图）与期望条数
_EXPECTED_DICTS = {
    'VW_DETECT_EQUIP_TYPE': 18,
    'VW_DEVICE_TYPE': 9,
    'VW_YES_NO_FLAG': 2,
    'VW_EQUIP_CLS': 25,
    'VW_EQUIP_CATEG': 10,
    'VW_DETECT_TYPE': 19,
    'VW_DMD_PLAN_TYPE': 2,
}


def _load_payload():
    if not PAYLOAD_PATH.exists():
        print(f"[跳过] 找不到测试报文: {PAYLOAD_PATH}")
        return None
    with open(PAYLOAD_PATH, encoding='utf-8') as f:
        return json.load(f)


def test_shapes():
    payload = _load_payload()
    if payload is None:
        return
    dfs = extract_request(payload)
    for key, shape in _EXPECTED_COLLECTIONS.items():
        assert dfs[key].shape == shape, f"{key} shape {dfs[key].shape} != {shape}"
    for key, n in _EXPECTED_DICTS.items():
        assert dfs[key].shape == (n, 3), f"{key} shape {dfs[key].shape} != ({n}, 3)"
    print(f"[shape] 9 个请求集合 + 7 个码值映射 shape 全部正确 - OK")


def test_device_code_string():
    payload = _load_payload()
    if payload is None:
        return
    dfs = extract_request(payload)
    arrive = dfs['arriveBatchList']
    # 设备码前导 0 必须保留为字符串
    assert '022606181429001' in set(arrive['equipCode']), "设备码前导0丢失"
    # sysNo 也是字符串
    assert set(dfs['deviceParaList']['sysNo'].dropna()) <= {'2001', '2101', '2201', '2301'}
    assert dfs['scheduleConfigList']['sysNo'].dtype == object, "sysNo 应保持字符串"
    print("[设备码] 前导 0 保留、sysNo 为字符串 - OK")


def test_date_and_time():
    payload = _load_payload()
    if payload is None:
        return
    dfs = extract_request(payload)
    arrive = dfs['arriveBatchList']
    # Java 日期格式 Wed Aug 05 00:00:00 CST 2026 解析为 2026-08-05
    got = arrive.loc[arrive['arriveBatchNo'] == '2012608051001968', 'arriveDate'].iloc[0]
    assert got == pd.Timestamp('2026-08-05 00:00:00'), f"Java 日期解析失败: {got}"
    # 空串 detectEquipType 归一为 NaN
    got = arrive.loc[arrive['arriveBatchNo'] == '2012606231001391', 'detectEquipType'].iloc[0]
    assert pd.isna(got), "空串 detectEquipType 未归一为 NaN"
    # 时间未补零原样保留
    assert dfs['scheduleTimeList']['startTime'].iloc[0] == '9:00', "时间被改写"
    assert dfs['scheduleTimeList']['workDay'].iloc[0] == pd.Timestamp('2026-08-07')
    print("[日期/时间] Java 日期解析、空串 NaN、时间原样 - OK")


def test_non_dmd_alias():
    payload = _load_payload()
    if payload is None:
        return
    dfs = extract_request(payload)
    nd = dfs['nonDmdAimEquipCodeCfgList']
    # 报文用 nonDmdTargetEquipCodeCfgVOList / allocationRation，须命中文档名/字段名
    assert len(nd) == 8, f"非需求集合别名未命中: {len(nd)}"
    assert nd['allocationRatio'].iloc[0] == 100, "allocationRation 字段别名未命中"
    assert nd['aimEquipCode'].iloc[0] == nd['equipCode'].iloc[0]
    print("[别名] nonDmd 集合名 + allocationRation 字段名双别名解析 - OK")


def test_empty_collection_keeps_columns():
    payload = _load_payload()
    if payload is None:
        return
    dfs = extract_request(payload)
    assert dfs['unqualifiedStockList'].shape == (0, 3), "空集合应保列结构"
    print("[空集合] unqualifiedStockList 保列 (0,3) - OK")


def test_empty_payload():
    dfs = extract_request({})
    # 空请求体：请求集合全为空表但保列，码值映射完整
    for key, cols in [('deviceParaList', 7), ('arriveBatchList', 8), ('unqualifiedStockList', 3)]:
        assert dfs[key].shape == (0, cols), f"空请求 {key} 未保列"
    assert dfs['VW_EQUIP_CLS'].shape == (25, 3), "空请求应返回完整码值映射"
    print("[空请求] 集合空表保列 + 码值映射完整 - OK")


def test_mapping_df_schema():
    payload = _load_payload()
    if payload is None:
        return
    dfs = extract_request(payload)
    for key in _EXPECTED_DICTS:
        df = dfs[key]
        assert list(df.columns) == ['编码', '名称', '说明'], f"{key} 列名不对: {list(df.columns)}"
        assert df['编码'].dtype == object, f"{key} 编码列应为字符串"
    print("[映射] 列 schema(编码/名称/说明) 与编码字符串类型 - OK")


if __name__ == '__main__':
    test_shapes()
    test_device_code_string()
    test_date_and_time()
    test_non_dmd_alias()
    test_empty_collection_keeps_columns()
    test_empty_payload()
    test_mapping_df_schema()
    print("\n=== extractor 测试全部通过 ===")
