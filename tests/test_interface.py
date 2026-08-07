# -*- coding: utf-8 -*-
"""
按接口说明.md 定义的格式测试算法服务接口。
========================================
运行方式（在项目根目录）：
    python tests/test_interface.py

说明：
- 入参构造使用接口文档的字段名（8 个集合）
- 通过 Flask test_client 直接调用路由，无需启动服务器
- 出参校验字段与接口文档 detectPlanSchedulingchList 完全一致
"""
import json
import sys
from pathlib import Path

# 把项目根目录加入 sys.path，保证 `from server import ...` 可解析
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import create_app  # noqa: E402

app = create_app()
INTERFACE_PATH = '/restful/busiInterface/ipsService/detectPlanScheduling'

# 接口文档出参 detectPlanSchedulingchList 的字段清单
EXPECTED_OUTPUT_FIELDS = [
    'sysNo', 'sysName', 'deviceType', 'deviceNo', 'arriveBatchNo',
    'equipCateg', 'equipCls', 'equipCode', 'equipDesc', 'detectSchemeId',
    'projectedStartTime', 'projectedEndTime', 'detectPlanQty',
    'demandFlag', 'weekDayStartAndEnd',
]


def build_payload():
    """构造符合接口文档格式的入参（8 个集合，字段名与文档一致）。"""
    return {
        "deviceParaList": [
            {"sysNo": "2001", "sysName": "电能表兼容终端自动化检定流水线",
             "deviceType": "05", "deviceNo": "DGNx001", "deviceName": "仓1",
             "detectEquipType": "03", "posNum": 48},
            {"sysNo": "2001", "sysName": "电能表兼容终端自动化检定流水线",
             "deviceType": "05", "deviceNo": "DGNx001", "deviceName": "仓1",
             "detectEquipType": "14", "posNum": 48},
            {"sysNo": "2001", "sysName": "电能表兼容终端自动化检定流水线",
             "deviceType": "03", "deviceNo": "DGNx002", "deviceName": "仓2",
             "detectEquipType": "14", "posNum": 48},
        ],
        "dmdPlanDetList": [
            {"dmdPlanDetId": 1, "dmdPlanNo": "P001", "planType": "01",
             "planYear": "2026", "planMonth": "03", "appOrg": "A001",
             "equipCateg": "C01", "equipCls": "智能量测终端",
             "equipCode": "EQ-TERM-1", "equipDesc": "智能量测终端",
             "pEquipCode": "EQ-TERM-1", "sumQty": 100, "detectEquipType": "14"},
        ],
        "arriveBatchList": [
            {"arriveBatchNo": "B0001", "equipCateg": "C01",
             "equipCls": "智能量测终端", "equipCode": "EQ-TERM-1",
             "equipDesc": "智能量测终端", "arriveQty": 100,
             "arriveDate": "2026-03-02 00:00:00", "detectEquipType": "14"},
        ],
        "detectSchList": [
            {"equipCode": "EQ-TERM-1", "detectType": "01",
             "detectSchemeId": 1001, "schTime": 414},
        ],
        "qualifiedStockList": [
            {"equipCode": "EQ-TERM-1", "lowerLimitQty": 0,
             "qualifiedQty": 0, "distLockQty": 0},
        ],
        "unqualifiedStockList": [],
        "scheduleTimeList": [
            {"workDay": "2026-03-01", "startTime": "09:00", "endTime": "17:00"},
            {"workDay": "2026-03-02", "startTime": "09:00", "endTime": "17:00"},
            {"workDay": "2026-03-03", "startTime": "09:00", "endTime": "17:00"},
            {"workDay": "2026-03-04", "startTime": "09:00", "endTime": "17:00"},
        ],
        "scheduleConfigList": [
            {"sysNo": "2001", "sysName": "电能表兼容终端自动化检定流水线",
             "timeInterval": 300, "overtime": 0},
        ],
    }


def test_normal():
    """正常排程：出参字段、值、总量均符合接口文档。"""
    client = app.test_client()
    resp = client.post(INTERFACE_PATH, json=build_payload())
    assert resp.status_code == 200, resp.status_code
    body = resp.get_json()

    assert body['resultFlag'] == '1', f"resultFlag 应为 1: {body}"
    rows = body['detectPlanSchedulingchList']
    assert rows, "无排程明细返回"

    for row in rows:
        assert set(row.keys()) == set(EXPECTED_OUTPUT_FIELDS), \
            f"出参字段与接口文档不一致: {sorted(row.keys())}"
        assert row['sysNo'] == '2001'
        assert row['sysName']
        assert row['deviceNo']
        assert row['equipCls'] == '智能量测终端'
        assert row['projectedStartTime'] and row['projectedEndTime']
        assert row['detectPlanQty'] > 0
        assert row['demandFlag'] in ('0', '1')

    total = sum(r['detectPlanQty'] for r in rows)
    assert total == 100, f"总排程量 {total} 应为 100"
    print(f"[正常] 生成 {len(rows)} 条排程明细，总量 {total} - OK")


def test_equipcls_code_spec_category():
    """equipCls 为编码（真实报文形态）时，spec 设备分类应按 detectEquipType 推断。

    回归：客户报文 equipCls 是 "01"/"06"/"08"/"19" 这类编码，此前被原样写进
    spec.设备分类，导致与算法 chambers 的中文分类名匹配不上而全部跳过、返回空集。
    现在应推断出中文分类名；equipCls 已是中文名时兜底保留。
    """
    from data.reader import read_json
    payload = {
        "deviceParaList": [
            {"sysNo": "2001", "sysName": "电表兼容终端线",
             "deviceType": "01", "deviceNo": "DGNx001", "deviceName": "仓1",
             "detectEquipType": "01", "posNum": 72},
        ],
        "dmdPlanDetList": [],
        "arriveBatchList": [
            {"arriveBatchNo": "B0001", "equipCateg": "C01", "equipCls": "01",
             "equipCode": "EQ-CODE-1", "equipDesc": "单相表", "arriveQty": 5,
             "arriveDate": "2026-08-06 00:00:00", "detectEquipType": "01"},
            {"arriveBatchNo": "B0002", "equipCateg": "C02", "equipCls": "06",
             "equipCode": "EQ-HGQ-1", "equipDesc": "互感器", "arriveQty": 2,
             "arriveDate": "2026-08-06 00:00:00", "detectEquipType": "06"},
            {"arriveBatchNo": "B0003", "equipCateg": "C03", "equipCls": "智能量测终端",
             "equipCode": "EQ-TERM-2", "equipDesc": "终端", "arriveQty": 3,
             "arriveDate": "2026-08-06 00:00:00", "detectEquipType": None},
        ],
        "detectSchList": [],
        "qualifiedStockList": [], "unqualifiedStockList": [],
        "scheduleTimeList": [
            {"workDay": "2026-08-06", "startTime": "09:00", "endTime": "17:00"},
        ],
        "scheduleConfigList": [
            {"sysNo": "2001", "sysName": "电表兼容终端线", "timeInterval": 300, "overtime": 0},
        ],
    }
    dfs = read_json(payload)
    spec = dfs['spec'].set_index('设备码')
    assert spec.loc['EQ-CODE-1', '设备分类'] == '单相电能表', "编码 equipCls=01 + detectEquipType=01 应推断为单相电能表"
    assert spec.loc['EQ-HGQ-1', '设备分类'] == '10kV电流互感器', "编码 equipCls=06 + detectEquipType=06 应推断为10kV电流互感器"
    assert spec.loc['EQ-TERM-2', '设备分类'] == '智能量测终端', "equipCls 已是中文名时应兜底保留"
    print("[equipCls编码] spec 设备分类按 detectEquipType 正确推断 - OK")


def test_empty_body():
    """空请求体：返回 resultFlag=0 及错误信息。"""
    client = app.test_client()
    resp = client.post(INTERFACE_PATH, json={})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['resultFlag'] == '0'
    assert body['errorInfo']
    print(f"[空请求体] resultFlag=0, errorInfo={body['errorInfo']!r} - OK")


def test_missing_required_sets():
    """缺少核心集合：算法服务应返回失败而不崩溃。"""
    client = app.test_client()
    # 只传需求，缺其他集合
    resp = client.post(INTERFACE_PATH, json={"dmdPlanDetList": []})
    assert resp.status_code == 200
    body = resp.get_json()
    assert 'resultFlag' in body
    print(f"[缺集合] resultFlag={body['resultFlag']} - OK")


def test_invalid_json():
    """非 JSON 请求体：返回 resultFlag=0。"""
    client = app.test_client()
    resp = client.post(INTERFACE_PATH, data='not-json', content_type='application/json')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['resultFlag'] == '0'
    print(f"[非法JSON] resultFlag=0, errorInfo={body['errorInfo']!r} - OK")


if __name__ == '__main__':
    test_normal()
    test_equipcls_code_spec_category()
    test_empty_body()
    test_missing_required_sets()
    test_invalid_json()
    print("\n=== 接口测试全部通过 ===")
