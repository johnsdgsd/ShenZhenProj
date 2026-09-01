"""到货计划排程 V0.0.6 JSON 出参映射。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .models import ArrivalResult


def _date_time(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(value, date):
        return f'{value.isoformat()} 00:00:00'
    return str(value or '')


def _number(value: Any) -> int | float:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return 0 if value is None else value


def write_json(result: ArrivalResult) -> dict[str, Any]:
    """只映射字段；净需求和其他业务统计均由 scheduler 计算。"""
    return {
        'resultFlag': '1',
        'errorInfo': '',
        'arrivePlanSchedulingchList': [{
            'arrivePlanDate': _date_time(r['arrival_plan_date']),
            'planYm': f"{r['plan_ym'][:4]}-{r['plan_ym'][4:]}",
            'planWeek': r['plan_week'],
            'equipCateg': r['equip_categ'],
            'equipCls': r['equip_cls'],
            'materialNo': r['material_no'],
            'equipCode': r['equip_code'],
            'equipDesc': r['equip_desc'],
            'supplierNo': r['supplier_no'],
            'contractId': r['contract_id'],
            'contractDetId': r['contract_detail_id'],
            'planQty': r['plan_qty'],
            'stockCycle': _number(r['stock_cycle']),
            'transitTime': _number(r['transit_time']),
        } for r in result.schedule_rows],
        'capAlarmList': [{
            'whAreaId': r['warehouse_area_id'],
            'whAreaName': r['warehouse_area_name'],
            'alarmDate': _date_time(r['alarm_date']),
            'inStockQty': r['in_stock_qty'],
            'whAreaCap': r['warehouse_area_capacity'],
            'overCapQty': r['over_capacity_qty'],
            'dayArriveQty': r['day_arrive_qty'],
            'dayBatchQty': r['day_batch_qty'],
        } for r in result.capacity_alarm_rows],
        'contractAllocationList': [{
            'materialNo': r['material_no'],
            'contractId': r['contract_id'],
            'contractDetId': r['contract_detail_id'],
            'supplierNo': r['supplier_no'],
            'supplierName': r['supplier_name'],
            'purchaseQty': r['purchase_qty'],
            'arriveQty': r['arrive_qty'],
            'executionProgress': r['execution_progress'],
            'contractRatio': r['contract_ratio'],
            'sameMaterialTotalProgress': r['same_material_total_progress'],
            'allocationQty': r['allocation_qty'],
            'afterAllocationProgress': r['after_allocation_progress'],
            'remainingContractQty': r['remaining_contract_qty'],
        } for r in result.contract_allocation_rows],
        'contractShortageAlarmList': [{
            'materialNo': r['material_no'],
            'dmdQty': r['demand_qty'],
            'purchaseTotalQty': r['purchase_total_qty'],
            'shortageQty': r['shortage_qty'],
            'alarmDate': _date_time(r['alarm_date']),
        } for r in result.contract_shortage_rows],
        'arriveAllocationList': [{
            # V0.0.6 没有 materialNo，按物资汇总后映射该物资关联的大码。
            'equipCode': r['equip_code'],
            'planYm': f"{r['plan_ym'][:4]}-{r['plan_ym'][4:]}",
            'dmdPlanQty': r['demand_plan_qty'],
            'supplyQty': r['supply_qty'],
            'inWhQty': r['in_wh_qty'],
            'netSupplyQty': r['net_supply_qty'],
            'unqualifiedQty': r['unqualified_qty'],
            'lowerLimitQty': r['lower_limit_qty'],
            'qualifiedQty': r['qualified_qty'],
            'distLockQty': r['dist_lock_qty'],
            'netQualifiedQty': r['net_qualified_qty'],
            'netDmdPlanQty': r['net_demand_plan_qty'],
        } for r in result.net_demand_rows],
    }
