"""到货计划排程数据准备与字段校验。"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict

import pandas as pd

from .models import PreparedArrivalData

logger = logging.getLogger(__name__)


def _missing(value: Any) -> bool:
    return value is None or value == '' or (isinstance(value, float) and pd.isna(value))


def _text(value: Any) -> str:
    if _missing(value):
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _required_text(row: dict[str, Any], set_name: str, index: int, field: str) -> str:
    value = _text(row.get(field))
    if not value:
        logger.warning('%s[%d] 缺少必填字段 %s', set_name, index, field)
        raise ValueError(f'{set_name}[{index}].{field} 不能为空')
    return value


def _int(value: Any, label: str, default: int = 0) -> int:
    if _missing(value):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        logger.warning('%s 不是有效整数: %r', label, value)
        raise ValueError(f'{label} 不是有效整数: {value!r}') from None


def _float(value: Any, label: str, default: float = 0.0) -> float:
    if _missing(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning('%s 不是有效数值: %r', label, value)
        raise ValueError(f'{label} 不是有效数值: {value!r}') from None


def _month(year: Any, month: Any, label: str) -> str:
    try:
        return f'{int(float(_text(year))):04d}{int(float(_text(month))):02d}'
    except (TypeError, ValueError):
        logger.warning('%s 年月格式错误: year=%r month=%r', label, year, month)
        raise ValueError(f'{label}.planYear/planMonth 格式错误') from None


def _date(value: Any, label: str, required: bool = True) -> date | None:
    if _missing(value):
        if required:
            logger.warning('%s 不能为空', label)
            raise ValueError(f'{label} 不能为空')
        return None
    parsed = pd.to_datetime(value, errors='coerce')
    if pd.isna(parsed):
        logger.warning('%s 日期格式错误: %r', label, value)
        raise ValueError(f'{label} 日期格式错误: {value!r}')
    return parsed.date()


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [] if frame is None or frame.empty else frame.to_dict(orient='records')


def _prepare_demands(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared = []
    for i, row in enumerate(rows):
        materials = row.get('materialNoList')
        if not isinstance(materials, list) or not materials:
            logger.warning('dmdPlanDetList[%d].materialNoList 缺失或为空', i)
            raise ValueError(f'dmdPlanDetList[{i}].materialNoList 至少需要一个物资编码')
        for j, item in enumerate(materials):
            if not isinstance(item, dict):
                raise TypeError(f'dmdPlanDetList[{i}].materialNoList[{j}] 必须是对象')
            prepared.append({
                'demand_detail_id': _required_text(row, 'dmdPlanDetList', i, 'dmdPlanDetId'),
                'demand_plan_no': _text(row.get('dmdPlanNo')),
                'plan_ym': _month(row.get('planYear'), row.get('planMonth'), f'dmdPlanDetList[{i}]'),
                'equip_categ': _required_text(row, 'dmdPlanDetList', i, 'equipCateg'),
                'equip_cls': _required_text(row, 'dmdPlanDetList', i, 'equipCls'),
                'equip_code': _required_text(row, 'dmdPlanDetList', i, 'equipCode'),
                'equip_desc': _text(row.get('equipDesc')),
                'parent_equip_code': _text(row.get('pEquipCode')) or _text(row.get('equipCode')),
                'quantity': _int(row.get('sumQty'), f'dmdPlanDetList[{i}].sumQty'),
                'material_no': _required_text(item, f'dmdPlanDetList[{i}].materialNoList', j, 'materialNo'),
                'material_desc': _text(item.get('materialDesc')),
            })
    return prepared


def _prepare_qualified(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for i, row in enumerate(rows):
        result.append({
            'equip_code': _required_text(row, 'qualifiedStockList', i, 'equipCode'),
            'parent_equip_code': _text(row.get('pEquipCode')) or _text(row.get('equipCode')),
            'lower_limit_qty': _int(row.get('lowerLimitQty'), f'qualifiedStockList[{i}].lowerLimitQty'),
            'qualified_qty': _int(row.get('qualifiedQty'), f'qualifiedStockList[{i}].qualifiedQty'),
            'dist_lock_qty': _int(row.get('distLockQty'), f'qualifiedStockList[{i}].distLockQty'),
        })
    return result


def _prepare_unqualified(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for i, row in enumerate(rows):
        result.append({
            'equip_code': _required_text(row, 'unqualifiedStockList', i, 'equipCode'),
            'arrive_batch_no': _text(row.get('arriveBatchNo')),
            'unqualified_qty': _int(row.get('unqualifiedQty'), f'unqualifiedStockList[{i}].unqualifiedQty'),
        })
    return result


def _prepare_contracts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for i, row in enumerate(rows):
        result.append({
            'contract_detail_id': _required_text(row, 'orderContractDetList', i, 'contractDetId'),
            'contract_id': _required_text(row, 'orderContractDetList', i, 'contractId'),
            'equip_categ': _required_text(row, 'orderContractDetList', i, 'equipCateg'),
            'equip_cls': _required_text(row, 'orderContractDetList', i, 'equipCls'),
            'material_no': _required_text(row, 'orderContractDetList', i, 'materialNo'),
            'purchase_qty': _int(row.get('purchaseQty'), f'orderContractDetList[{i}].purchaseQty'),
            'arrive_qty': _int(row.get('arriveQty'), f'orderContractDetList[{i}].arriveQty'),
            'supplier_no': _required_text(row, 'orderContractDetList', i, 'supplierNo'),
            'supplier_name': _text(row.get('supplierName')),
        })
    return result


def _prepare_notices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for i, row in enumerate(rows):
        result.append({
            'supply_notice_detail_id': _required_text(row, 'supplyNoticeDetList', i, 'supplyNoticeDetId'),
            'supply_notice_id': _required_text(row, 'supplyNoticeDetList', i, 'supplyNoticeId'),
            'supplier_no': _required_text(row, 'supplyNoticeDetList', i, 'supplierNo'),
            'supplier_name': _text(row.get('supplierName')),
            'contract_detail_id': _required_text(row, 'supplyNoticeDetList', i, 'contractDetId'),
            'material_no': _required_text(row, 'supplyNoticeDetList', i, 'materialNo'),
            'equip_code': _required_text(row, 'supplyNoticeDetList', i, 'equipCode'),
            'supply_qty': _int(row.get('supplyQty'), f'supplyNoticeDetList[{i}].supplyQty'),
            'in_wh_qty': _int(row.get('inWhQty'), f'supplyNoticeDetList[{i}].inWhQty'),
            'required_arrive_date': _date(row.get('reqArriveDate'), f'supplyNoticeDetList[{i}].reqArriveDate'),
        })
    return result


def _prepare_suppliers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for i, row in enumerate(rows):
        result.append({
            'supplier_no': _required_text(row, 'supplierConfigList', i, 'supplierNo'),
            'supplier_name': _text(row.get('supplierName')),
            'stock_cycle': _float(row.get('stockCycle'), f'supplierConfigList[{i}].stockCycle'),
            'transit_time': _float(row.get('transitTime'), f'supplierConfigList[{i}].transitTime'),
            'overall_score': _float(row.get('overallScore'), f'supplierConfigList[{i}].overallScore'),
            'week_max_count': max(1, _int(row.get('weekMaxCount'), f'supplierConfigList[{i}].weekMaxCount', 1)),
            'month_max_count': max(1, _int(row.get('monthMaxCount'), f'supplierConfigList[{i}].monthMaxCount', 999)),
        })
    return result


def _prepare_areas(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for i, row in enumerate(rows):
        result.append({
            'warehouse_area_id': _required_text(row, 'whAreaConfigList', i, 'whAreaId'),
            'warehouse_area_name': _required_text(row, 'whAreaConfigList', i, 'whAreaName'),
            'warehouse_area_type': _required_text(row, 'whAreaConfigList', i, 'whAreaType'),
            'capacity': _int(row.get('whAreaCap'), f'whAreaConfigList[{i}].whAreaCap'),
            'current_stock': _int(row.get('inStockQty'), f'whAreaConfigList[{i}].inStockQty'),
            'daily_batch_limit': max(1, _int(row.get('arriveBatchQty'), f'whAreaConfigList[{i}].arriveBatchQty')),
        })
    return result


def _prepare_workdays(rows: list[dict[str, Any]]) -> list[date]:
    workdays = sorted({_date(row.get('workDay'), f'scheduleTimeList[{i}].workDay') for i, row in enumerate(rows)})
    if not workdays:
        logger.warning('scheduleTimeList 为空')
        raise ValueError('scheduleTimeList 至少需要一个工作日')
    return workdays


def process_data(dfs: Dict[str, pd.DataFrame]) -> PreparedArrivalData:
    """把接口 DataFrame 转换为 8.24 业务层结构。"""
    data = PreparedArrivalData(
        demands=_prepare_demands(_records(dfs['dmdPlanDetList'])),
        qualified_stock=_prepare_qualified(_records(dfs['qualifiedStockList'])),
        unqualified_stock=_prepare_unqualified(_records(dfs['unqualifiedStockList'])),
        contracts=_prepare_contracts(_records(dfs['orderContractDetList'])),
        supply_notices=_prepare_notices(_records(dfs['supplyNoticeDetList'])),
        suppliers=_prepare_suppliers(_records(dfs['supplierConfigList'])),
        warehouse_areas=_prepare_areas(_records(dfs['whAreaConfigList'])),
        workdays=_prepare_workdays(_records(dfs['scheduleTimeList'])),
    )
    logger.info(
        '到货数据准备完成：需求=%d 合同=%d 供应商=%d 工作日=%d',
        len(data.demands), len(data.contracts), len(data.suppliers), len(data.workdays),
    )
    return data
