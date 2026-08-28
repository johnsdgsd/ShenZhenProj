# -*- coding: utf-8 -*-
"""
按接口说明.md 定义的格式测试算法服务接口。
========================================
运行方式（在项目根目录）：
    python tests/test_interface.py

说明：
- 入参构造使用接口文档的字段名（9 个集合）
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

# 接口文档出参 detectPlanSchedulingchList 的字段清单（接口说明v0.0.6 §出参，17 字段）
EXPECTED_OUTPUT_FIELDS = [
    'sysNo', 'sysName', 'deviceType', 'deviceNo', 'arriveBatchNo',
    'equipCateg', 'equipCls', 'equipCode', 'equipDesc', 'aimEquipCode',
    'detectSchemeId', 'projectedStartTime', 'projectedEndTime', 'detectPlanQty',
    'demandFlag', 'weekDayStartAndEnd', 'detectType',
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
             "arriveDate": "2026-03-02 00:00:00", "detectEquipType": "14",
             "sampleFlag": "1", "sampleQty": 0},   # v0.0.6：已抽检，不触发抽样
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
        # 8.16 码值适配：equipCls / equipCateg 由中文名改输出 VW_* 编码（零填充字符串）
        assert row['equipCls'] == '19', f"equipCls 应为 VW_EQUIP_CLS 编码: {row}"
        assert row['equipCateg'] == '09', f"equipCateg 应为 VW_EQUIP_CATEG 编码: {row}"
        # deviceType 来自 检定仓类型编码（VW_DEVICE_TYPE 码）；本用例 100 台分落
        # 仓类型 03（终端检定仓）与 05（三相表兼容终端检定仓）两仓
        assert row['deviceType'] in ('03', '05'), f"deviceType 应为 VW_DEVICE_TYPE 编码: {row}"
        assert row['projectedStartTime'] and row['projectedEndTime']
        assert row['detectPlanQty'] > 0
        assert row['demandFlag'] in ('0', '1')
        # 需求设备=自身码，非需求设备=分配目标码（v2.0 §1.3）
        assert row['aimEquipCode'] == row['equipCode'], f"aimEquipCode 应等于 equipCode: {row}"
        # 8.17：detectSchemeId 来自 detectSchList.detectSchemeId（spec.参数标识）
        assert row['detectSchemeId'] == 1001, f"detectSchemeId 应为入参方案标识 1001: {row}"
        # 8.25：detectType 出参（已抽检批次 → 03 首次检定）
        assert row['detectType'] == '03', f"detectType 应为首次检定码 03: {row}"

    total = sum(r['detectPlanQty'] for r in rows)
    assert total == 100, f"总排程量 {total} 应为 100"
    assert set(r['deviceType'] for r in rows) == {'03', '05'}, \
        f"100 台应分落两仓（deviceType 03/05）: {set(r['deviceType'] for r in rows)}"
    print(f"[正常] 生成 {len(rows)} 条排程明细，总量 {total}，aimEquipCode=自身码，"
          f"equipCls/equipCateg/deviceType 均为码值 - OK")


def test_equipcls_code_spec_category():
    """equipCls 为编码（真实报文形态）时，spec 设备分类应按 detectEquipType 推断。

    回归：客户报文 equipCls 是 "01"/"06"/"08"/"19" 这类编码，此前被原样写进
    spec.设备分类，导致与算法 chambers 的中文分类名匹配不上而全部跳过、返回空集。
    现在应推断出中文分类名；equipCls 已是中文名时兜底保留。
    """
    from modules.detect.reader import read_json
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
            # 0812 真实场景：equipCls 是编码且 detectEquipType 为空，靠 码→名 兜底
            {"arriveBatchNo": "B0004", "equipCateg": "C01", "equipCls": "01",
             "equipCode": "EQ-SINGLE-1", "equipDesc": "单相表", "arriveQty": 2,
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
    assert spec.loc['EQ-SINGLE-1', '设备分类'] == '单相电能表', "equipCls 编码=01 且 detectEquipType 为空（0812 场景）应码→名转出单相电能表"
    print("[equipCls编码] spec 设备分类按 detectEquipType 推断 / equipCls 码→名兜底（含 0812 空 detectEquipType 场景）- OK")


def test_detect_scheme_id_big_code_fallback():
    """8.17 get_detect_scheme_id 大小码匹配：小码查不到时回退大码，再查不到返回 None。"""
    from modules.detect.constants import SchedulingConfig
    from modules.detect.prepare import process_data
    from modules.detect.reader import read_json
    import modules.detect.scheduler as scheduler

    payload = {
        "deviceParaList": [
            {"sysNo": "2001", "sysName": "单相线", "deviceType": "01",
             "deviceNo": "DGNx001", "deviceName": "仓1",
             "detectEquipType": "01", "posNum": 48},
        ],
        "dmdPlanDetList": [
            {"planYear": "2026", "planMonth": "08", "equipCls": "01",
             "equipCode": "SMALL-1", "pEquipCode": "BIG-1", "sumQty": 1},
        ],
        "arriveBatchList": [],
        # detectSchList 只挂大码的方案标识；小码须经 大小码映射 回退命中
        "detectSchList": [
            {"equipCode": "BIG-1", "detectType": "03", "detectSchemeId": 3003, "schTime": 108},
        ],
        "qualifiedStockList": [], "unqualifiedStockList": [],
        "scheduleTimeList": [
            {"workDay": "2026-08-18", "startTime": "09:00", "endTime": "17:00"},
        ],
        "scheduleConfigList": [
            {"sysNo": "2001", "sysName": "单相线", "timeInterval": 300, "overtime": 0},
        ],
    }
    dfs = read_json(payload)
    process_data(dfs, SchedulingConfig())
    assert scheduler.get_detect_scheme_id('BIG-1') == 3003, "大码直查应命中"
    assert scheduler.get_detect_scheme_id('SMALL-1') == 3003, "小码应经大小码映射回退命中"
    assert scheduler.get_detect_scheme_id('NOPE') is None, "无映射应返回 None"
    print("[detectSchemeId] 直查 / 大小码回退 / 无映射返回 None - OK")


def test_sampling_flow():
    """8.25 抽检流程：未抽检批次先抽检（detectType=02）再做首检（03），首检不早于抽检完成。"""
    payload = {
        "deviceParaList": [
            {"sysNo": "2001", "sysName": "单相线", "deviceType": "01",
             "deviceNo": "DGNx001", "deviceName": "仓1",
             "detectEquipType": "01", "posNum": 48},
        ],
        "dmdPlanDetList": [],
        "arriveBatchList": [
            {"arriveBatchNo": "B-SMP-1", "equipCateg": "C01", "equipCls": "01",
             "equipCode": "SMALL-1", "equipDesc": "单相表", "arriveQty": 10,
             "arriveDate": "2026-08-06 00:00:00", "detectEquipType": "01",
             "sampleFlag": "0", "sampleQty": 3},   # 未抽检 → 先抽检 3 台
        ],
        "detectSchList": [],
        "qualifiedStockList": [], "unqualifiedStockList": [],
        "scheduleTimeList": [
            {"workDay": "2026-08-06", "startTime": "09:00", "endTime": "17:00"},
        ],
        "scheduleConfigList": [
            {"sysNo": "2001", "sysName": "单相线", "timeInterval": 300, "overtime": 0},
        ],
    }
    client = app.test_client()
    resp = client.post(INTERFACE_PATH, json=payload)
    assert resp.status_code == 200
    rows = resp.get_json()['detectPlanSchedulingchList']
    assert rows, "无排程明细"
    types = {r['detectType'] for r in rows}
    assert '02' in types, f"应含抽检明细（detectType=02）: {types}"
    assert '03' in types, f"应含首检明细（detectType=03）: {types}"
    sample_rows = sorted([r for r in rows if r['detectType'] == '02'],
                         key=lambda r: r['projectedEndTime'])
    first_rows = [r for r in rows if r['detectType'] == '03']
    assert sum(r['detectPlanQty'] for r in sample_rows) == 3, "抽检数量应为 3 台"
    sample_end = sample_rows[-1]['projectedEndTime']
    for r in first_rows:
        assert r['projectedStartTime'] >= sample_end, \
            f"首检 {r['projectedStartTime']} 不应早于抽检完成 {sample_end}"
    print(f"[抽检流程] 未抽检批次先抽检 3 台（02）后首检 10 台（03），首检不早于抽检完成 - OK")


def test_sampling_default_sampled():
    """8.25 抽检默认值：缺 sampleFlag 视为已抽检，不产生 detectType=02 明细。"""
    payload = {
        "deviceParaList": [
            {"sysNo": "2001", "sysName": "单相线", "deviceType": "01",
             "deviceNo": "DGNx001", "deviceName": "仓1",
             "detectEquipType": "01", "posNum": 48},
        ],
        "dmdPlanDetList": [],
        "arriveBatchList": [
            {"arriveBatchNo": "B-NOSMP-1", "equipCateg": "C01", "equipCls": "01",
             "equipCode": "SMALL-2", "equipDesc": "单相表", "arriveQty": 5,
             "arriveDate": "2026-08-06 00:00:00", "detectEquipType": "01"},
            # 无 sampleFlag/sampleQty（旧报文形态）→ 默认已抽检
        ],
        "detectSchList": [],
        "qualifiedStockList": [], "unqualifiedStockList": [],
        "scheduleTimeList": [
            {"workDay": "2026-08-06", "startTime": "09:00", "endTime": "17:00"},
        ],
        "scheduleConfigList": [
            {"sysNo": "2001", "sysName": "单相线", "timeInterval": 300, "overtime": 0},
        ],
    }
    client = app.test_client()
    resp = client.post(INTERFACE_PATH, json=payload)
    rows = resp.get_json()['detectPlanSchedulingchList']
    assert rows, "无排程明细"
    assert all(r['detectType'] == '03' for r in rows), "缺 sampleFlag 应默认已抽检，不出 02 明细"
    print("[抽检默认值] 缺 sampleFlag 视为已抽检，全部为首次检定（03）- OK")


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
    test_detect_scheme_id_big_code_fallback()
    test_sampling_flow()
    test_sampling_default_sampled()
    test_empty_body()
    test_missing_required_sets()
    test_invalid_json()
    print("\n=== 接口测试全部通过 ===")
