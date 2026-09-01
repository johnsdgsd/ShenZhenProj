# -*- coding: utf-8 -*-
"""V0.0.6 到货计划排程 HTTP 与 8.24 业务规则回归测试。"""
from __future__ import annotations

import sys
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.arrival.pipeline import run_pipeline  # noqa: E402
from modules.arrival.reader import read_json  # noqa: E402
from server import create_app  # noqa: E402


INTERFACE_PATH = '/restful/busiInterface/ipsService/arrivePlanScheduling'
TOP_LEVEL_FIELDS = {
    'resultFlag', 'errorInfo', 'arrivePlanSchedulingchList', 'capAlarmList',
    'contractAllocationList', 'contractShortageAlarmList', 'arriveAllocationList',
}
NET_FIELDS = {
    'equipCode', 'planYm', 'dmdPlanQty', 'supplyQty', 'inWhQty', 'netSupplyQty',
    'unqualifiedQty', 'lowerLimitQty', 'qualifiedQty', 'distLockQty',
    'netQualifiedQty', 'netDmdPlanQty',
}
SCHEDULE_FIELDS = {
    'arrivePlanDate', 'planYm', 'planWeek', 'equipCateg', 'equipCls',
    'materialNo', 'equipCode', 'equipDesc', 'supplierNo', 'contractId',
    'contractDetId', 'planQty', 'stockCycle', 'transitTime',
}


def build_payload():
    return {
        'dmdPlanDetList': [{
            'dmdPlanDetId': 1, 'dmdPlanNo': 'DMD-001', 'planType': '01',
            'planYear': '2026', 'planMonth': '08', 'appOrg': 'ORG-001',
            'equipCateg': '01', 'equipCls': '01', 'equipCode': 'EQ-001',
            'equipDesc': '单相智能电能表', 'pEquipCode': 'EQ-BIG-001', 'sumQty': 100,
            'materialNoList': [{'materialNo': 'MAT-001', 'materialDesc': '物资一'}],
        }],
        'qualifiedStockList': [{
            'equipCode': 'EQ-001', 'pEquipCode': 'EQ-BIG-001',
            'lowerLimitQty': 5, 'qualifiedQty': 30, 'distLockQty': 5,
        }],
        'unqualifiedStockList': [{
            'equipCode': 'EQ-001', 'arriveBatchNo': 'ARR-001', 'unqualifiedQty': 10,
        }],
        'orderContractDetList': [{
            'contractDetId': '101', 'contractId': '10', 'equipCateg': '01',
            'equipCls': '01', 'materialNo': 'MAT-001', 'purchaseQty': 100,
            'arriveQty': 20, 'supplierNo': 'SUP-001', 'supplierName': '测试供应商',
        }],
        'supplyNoticeDetList': [{
            'supplyNoticeDetId': '201', 'supplyNoticeId': '20', 'supplierNo': 'SUP-001',
            'supplierName': '测试供应商', 'contractDetId': '101', 'materialNo': 'MAT-001',
            'equipCode': 'EQ-001', 'supplyQty': 15, 'inWhQty': 5,
            'reqArriveDate': '2026-08-03',
        }],
        'supplierConfigList': [{
            'supplierNo': 'SUP-001', 'supplierName': '测试供应商', 'stockCycle': 0,
            'transitTime': 0, 'overallScore': 98.5, 'weekMaxCount': 2,
            'monthMaxCount': 4,
        }],
        'whAreaConfigList': [{
            'whAreaId': '301', 'whAreaName': '计量管理所待检仓', 'whAreaType': '01',
            'whAreaCap': 1000, 'inStockQty': 100, 'arriveBatchQty': 3,
        }],
        'scheduleTimeList': [
            {'workDay': f'2026-08-{day:02d}', 'startTime': '09:00', 'endTime': '17:00'}
            for day in range(3, 15)
        ],
    }


def _business_result(payload):
    return run_pipeline(read_json(payload))


def test_normal():
    response = create_app().test_client().post(INTERFACE_PATH, json=build_payload())
    assert response.status_code == 200
    body = response.get_json()
    assert body['resultFlag'] == '1', body
    assert set(body) == TOP_LEVEL_FIELDS
    assert len(body['arriveAllocationList']) == 1
    summary = body['arriveAllocationList'][0]
    assert set(summary) == NET_FIELDS
    assert summary == {
        'equipCode': 'EQ-BIG-001', 'planYm': '2026-08', 'dmdPlanQty': 100,
        'supplyQty': 15, 'inWhQty': 5, 'netSupplyQty': 10,
        'unqualifiedQty': 10, 'lowerLimitQty': 5, 'qualifiedQty': 30,
        'distLockQty': 5, 'netQualifiedQty': 20, 'netDmdPlanQty': 60,
    }
    assert body['arrivePlanSchedulingchList']
    assert all(set(row) == SCHEDULE_FIELDS for row in body['arrivePlanSchedulingchList'])
    assert sum(row['planQty'] for row in body['arrivePlanSchedulingchList']) == 60
    assert sum(row['allocationQty'] for row in body['contractAllocationList']) == 60
    assert body['contractShortageAlarmList'] == []


def test_missing_set_and_field():
    payload = build_payload()
    payload.pop('qualifiedStockList')
    body = create_app().test_client().post(INTERFACE_PATH, json=payload).get_json()
    assert body['resultFlag'] == '0'
    assert 'qualifiedStockList' in body['errorInfo']

    payload = build_payload()
    payload['dmdPlanDetList'][0].pop('equipCode')
    body = create_app().test_client().post(INTERFACE_PATH, json=payload).get_json()
    assert body['resultFlag'] == '0'
    assert 'equipCode' in body['errorInfo']


def test_first_month_deducts_all_and_negative_qualified_is_kept():
    payload = build_payload()
    payload['qualifiedStockList'][0].update({'qualifiedQty': 5, 'distLockQty': 10, 'lowerLimitQty': 5})
    second = deepcopy(payload['dmdPlanDetList'][0])
    second.update({'dmdPlanDetId': 2, 'planMonth': '09', 'sumQty': 50})
    payload['dmdPlanDetList'].append(second)
    payload['scheduleTimeList'] += [
        {'workDay': f'2026-09-{day:02d}', 'startTime': '09:00', 'endTime': '17:00'}
        for day in range(1, 15)
    ]
    summaries = create_app().test_client().post(INTERFACE_PATH, json=payload).get_json()['arriveAllocationList']
    assert [row['planYm'] for row in summaries] == ['2026-08', '2026-09']
    assert summaries[0]['netQualifiedQty'] == -10
    assert summaries[0]['netDmdPlanQty'] == 90  # 100 - 10供货 - 10非合格 - (-10)
    assert summaries[1]['netDmdPlanQty'] == 50
    assert summaries[1]['netQualifiedQty'] == 0
    assert summaries[1]['netSupplyQty'] == 0


def test_notice_date_excluded_and_daily_limit():
    payload = build_payload()
    result = _business_result(payload)
    assert all(row['arrival_plan_date'].isoformat() != '2026-08-03' for row in result.schedule_rows)
    batches_by_day = defaultdict(set)
    for row in result.schedule_rows:
        batches_by_day[row['arrival_plan_date']].add(row['_batch_no'])
    assert all(len(batch_numbers) <= 3 for batch_numbers in batches_by_day.values())
    assert result.daily_batch_alert_rows == []


def test_frequency_is_supplier_plus_big_code_and_monthly_limit():
    payload = build_payload()
    payload['supplyNoticeDetList'] = []
    payload['qualifiedStockList'] = []
    payload['unqualifiedStockList'] = []
    payload['supplierConfigList'][0].update({'weekMaxCount': 1, 'monthMaxCount': 1})
    second_demand = deepcopy(payload['dmdPlanDetList'][0])
    second_demand.update({
        'dmdPlanDetId': 2, 'equipCode': 'EQ-002', 'pEquipCode': 'EQ-BIG-002',
        'sumQty': 20, 'materialNoList': [{'materialNo': 'MAT-002', 'materialDesc': '物资二'}],
    })
    payload['dmdPlanDetList'].append(second_demand)
    second_contract = deepcopy(payload['orderContractDetList'][0])
    second_contract.update({
        'contractDetId': '102', 'contractId': '11', 'materialNo': 'MAT-002',
        'purchaseQty': 20, 'arriveQty': 0,
    })
    payload['orderContractDetList'].append(second_contract)
    result = _business_result(payload)
    batches = {(row['_batch_no'], row['_big_code']) for row in result.schedule_rows}
    assert {big for _, big in batches} == {'EQ-BIG-001', 'EQ-BIG-002'}
    assert len(batches) == 2  # 同供应商两个大码各可排 1 批，不是供应商整体只能 1 批


def test_cross_month_iso_week_counter_not_reset():
    payload = build_payload()
    payload['supplyNoticeDetList'] = []
    payload['qualifiedStockList'] = []
    payload['unqualifiedStockList'] = []
    payload['supplierConfigList'][0].update({'weekMaxCount': 1, 'monthMaxCount': 4})
    payload['dmdPlanDetList'][0].update({'planMonth': '03', 'sumQty': 10})
    second = deepcopy(payload['dmdPlanDetList'][0])
    second.update({'dmdPlanDetId': 2, 'planMonth': '04', 'sumQty': 10})
    payload['dmdPlanDetList'].append(second)
    payload['orderContractDetList'][0].update({'purchaseQty': 20, 'arriveQty': 0})
    payload['scheduleTimeList'] = [
        {'workDay': day, 'startTime': '09:00', 'endTime': '17:00'}
        for day in ('2026-03-30', '2026-03-31', '2026-04-01', '2026-04-02', '2026-04-06')
    ]
    result = _business_result(payload)
    batch_dates = {row['_batch_no']: row['arrival_plan_date'] for row in result.schedule_rows}
    assert any(day.month == 3 and day.isocalendar().week == 14 for day in batch_dates.values())
    assert any(day.month == 4 and day.isocalendar().week == 15 for day in batch_dates.values())
    batches_by_week = defaultdict(set)
    for row in result.schedule_rows:
        iso = row['arrival_plan_date'].isocalendar()
        batches_by_week[(row['supplier_no'], row['_big_code'], iso.year, iso.week)].add(row['_batch_no'])
    assert all(len(batch_numbers) <= 1 for batch_numbers in batches_by_week.values())


def test_duplicate_contract_detail_ids_do_not_mix_materials():
    payload = build_payload()
    payload['supplyNoticeDetList'] = []
    payload['qualifiedStockList'] = []
    payload['unqualifiedStockList'] = []
    second_demand = deepcopy(payload['dmdPlanDetList'][0])
    second_demand.update({
        'dmdPlanDetId': 2, 'equipCode': 'EQ-002', 'pEquipCode': 'EQ-BIG-002',
        'sumQty': 30, 'materialNoList': [{'materialNo': 'MAT-002', 'materialDesc': '物资二'}],
    })
    payload['dmdPlanDetList'].append(second_demand)
    payload['orderContractDetList'][0].update({'purchaseQty': 100, 'arriveQty': 0})
    second_contract = deepcopy(payload['orderContractDetList'][0])
    second_contract.update({'contractId': '11', 'materialNo': 'MAT-002', 'purchaseQty': 30})
    payload['orderContractDetList'].append(second_contract)
    body = create_app().test_client().post(INTERFACE_PATH, json=payload).get_json()
    assert body['resultFlag'] == '1', body
    allocated = {row['materialNo']: row['allocationQty'] for row in body['contractAllocationList']}
    assert allocated == {'MAT-001': 100, 'MAT-002': 30}


def test_no_contract_creates_shortage_alarm():
    payload = build_payload()
    payload['orderContractDetList'] = []
    body = create_app().test_client().post(INTERFACE_PATH, json=payload).get_json()
    assert body['resultFlag'] == '1'
    assert body['contractShortageAlarmList'][0]['shortageQty'] == 60


def test_detect_route_unchanged():
    paths = {rule.rule for rule in create_app().url_map.iter_rules()}
    assert '/restful/busiInterface/ipsService/detectPlanScheduling' in paths
    assert INTERFACE_PATH in paths


if __name__ == '__main__':
    test_normal()
    test_missing_set_and_field()
    test_first_month_deducts_all_and_negative_qualified_is_kept()
    test_notice_date_excluded_and_daily_limit()
    test_frequency_is_supplier_plus_big_code_and_monthly_limit()
    test_cross_month_iso_week_counter_not_reset()
    test_duplicate_contract_detail_ids_do_not_mix_materials()
    test_no_contract_creates_shortage_alarm()
    test_detect_route_unchanged()
    print('=== 到货接口与 8.24 规则测试全部通过 ===')
