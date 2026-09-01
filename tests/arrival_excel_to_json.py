# -*- coding: utf-8 -*-
"""把到货排程 8-sheet Excel 转成 V0.0.6 HTTP 请求 JSON。

用法：
    python -X utf8 tests/arrival_excel_to_json.py --input docs/样例/到货计划排程入参.xlsx \
        --output docs/报文/到货计划排程_请求示例_0825.xlsx转换.json

Excel 没有 whAreaId，转换器按工作表行号生成 1、2、3……；正式接入前应由平台
提供真实库区标识。
"""
from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from datetime import datetime, time
from pathlib import Path
from typing import Any

import pandas as pd


SHEETS = {
    'demand': '月度需用',
    'qualified': '合格品库存详情（立库+成品仓）',
    'unqualified': '非合格品库存详情（待检仓+立库）',
    'contracts': '订单合同清单',
    'notices': '已供货通知物资',
    'suppliers': '供应商信息',
    'areas': '库区容量',
    'workdays': '库房排程时间',
}

SPEC_FIELDS = {
    'dmdPlanDetList': ({
        'dmdPlanDetId', 'dmdPlanNo', 'planType', 'planYear', 'planMonth', 'appOrg',
        'equipCateg', 'equipCls', 'equipCode', 'equipDesc', 'pEquipCode', 'sumQty',
        'materialNoList',
    }, set()),
    'qualifiedStockList': ({
        'equipCode', 'pEquipCode', 'lowerLimitQty', 'qualifiedQty', 'distLockQty',
    }, set()),
    'unqualifiedStockList': ({'equipCode', 'arriveBatchNo', 'unqualifiedQty'}, set()),
    'orderContractDetList': ({
        'contractDetId', 'contractId', 'equipCateg', 'equipCls', 'materialNo',
        'purchaseQty', 'arriveQty', 'supplierNo', 'supplierName',
    }, set()),
    'supplyNoticeDetList': ({
        'supplyNoticeDetId', 'supplyNoticeId', 'supplierNo', 'contractDetId',
        'materialNo', 'equipCode', 'supplyQty', 'inWhQty', 'reqArriveDate',
    }, {'supplierName'}),
    'supplierConfigList': ({
        'supplierNo', 'stockCycle', 'transitTime', 'overallScore',
        'weekMaxCount', 'monthMaxCount',
    }, {'supplierName'}),
    'whAreaConfigList': ({
        'whAreaId', 'whAreaName', 'whAreaType', 'whAreaCap', 'inStockQty', 'arriveBatchQty',
    }, set()),
    'scheduleTimeList': ({'workDay', 'startTime', 'endTime'}, set()),
}


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value))


def _text(value: Any) -> str:
    if _missing(value):
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _int(value: Any, default: int = 0) -> int:
    if _missing(value) or value == '':
        return default
    return int(float(value))


def _number(value: Any, default: float = 0.0) -> int | float:
    if _missing(value) or value == '':
        return default
    result = float(value)
    return int(result) if result.is_integer() else result


def _date(value: Any) -> str:
    return pd.Timestamp(value).strftime('%Y-%m-%d')


def _clock(value: Any) -> str:
    if _missing(value):
        return ''
    if isinstance(value, time):
        return value.strftime('%H:%M')
    if isinstance(value, (int, float)):
        seconds = int(round(float(value) * 24 * 60 * 60)) % (24 * 60 * 60)
        return f'{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}'
    parsed = pd.to_datetime(str(value), errors='coerce')
    return parsed.strftime('%H:%M') if not pd.isna(parsed) else str(value)[:5]


def _clean(frame: pd.DataFrame) -> pd.DataFrame:
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame


def _read(path: Path) -> dict[str, pd.DataFrame]:
    converters = {
        '物资编码': _text, '设备类型码': _text, '设备类型码大码': _text,
        '需求计划编号': _text, '申请单位码值': _text, '合同明细标识': _text,
        '合同标识': _text, '供应商编号': _text, '供货通知编号': _text,
        '供货通知明细标识': _text, '到货批次号': _text,
    }
    return {
        key: _clean(pd.read_excel(path, sheet_name=sheet, converters=converters))
        for key, sheet in SHEETS.items()
    }


def build_payload(input_path: Path) -> dict[str, list[dict[str, Any]]]:
    frames = _read(Path(input_path))
    payload: dict[str, list[dict[str, Any]]] = {}

    # 相同需求主信息下的多个物资编码合并到 materialNoList；数量仍属于该需求明细。
    grouped: OrderedDict[tuple, dict[str, Any]] = OrderedDict()
    for _, row in frames['demand'].iterrows():
        month = _text(row['所属月份'])
        key = (
            month, _text(row['配送类型']), _text(row['需求计划编号']),
            _text(row['申请单位']), _text(row['申请单位码值']),
            _text(row['设备类别']), _text(row['设备分类']), _text(row['设备类型码']),
            _text(row['设备类型码描述']), _text(row['设备类型码大码']), _int(row['计划数量']),
        )
        if key not in grouped:
            grouped[key] = {
                'dmdPlanDetId': len(grouped) + 1,
                'dmdPlanNo': key[2],
                'planType': '01',
                'planYear': month[:4],
                'planMonth': month[4:6],
                'appOrg': key[4] or key[3],
                'equipCateg': key[5],
                'equipCls': key[6],
                'equipCode': key[7],
                'equipDesc': key[8],
                'pEquipCode': key[9],
                'sumQty': key[10],
                'materialNoList': [],
            }
        material = {'materialNo': _text(row['物资编码']), 'materialDesc': ''}
        if material not in grouped[key]['materialNoList']:
            grouped[key]['materialNoList'].append(material)
    payload['dmdPlanDetList'] = list(grouped.values())

    payload['qualifiedStockList'] = [{
        'equipCode': _text(row['设备类型码']),
        'pEquipCode': _text(row['设备类型码大码']),
        'lowerLimitQty': _int(row['安全库存']),
        'qualifiedQty': _int(row['合格在库库存']),
        'distLockQty': _int(row['未配送库存']),
    } for _, row in frames['qualified'].iterrows()]

    payload['unqualifiedStockList'] = [{
        'equipCode': _text(row['设备类型码']),
        'arriveBatchNo': _text(row['到货批次号']),
        'unqualifiedQty': _int(row['非合格在库库存']),
    } for _, row in frames['unqualified'].iterrows()]

    payload['orderContractDetList'] = [{
        'contractDetId': _text(row['合同明细标识']),
        'contractId': _text(row['合同标识']),
        'equipCateg': _text(row['设备类别']),
        'equipCls': _text(row['设备分类']),
        'materialNo': _text(row['物资编码']),
        'purchaseQty': _int(row['合同数量']),
        'arriveQty': _int(row['已到货数量']),
        'supplierNo': _text(row['供应商编号']),
        'supplierName': _text(row['供应商名称']),
    } for _, row in frames['contracts'].iterrows()]

    payload['supplyNoticeDetList'] = [{
        'supplyNoticeDetId': _text(row['供货通知明细标识']),
        'supplyNoticeId': _text(row['供货通知编号']),
        'supplierNo': _text(row['供应商编号']),
        'supplierName': _text(row['供应商名称']),
        'contractDetId': _text(row['合同明细标识']),
        'materialNo': _text(row['物资编码']),
        'equipCode': _text(row['设备类型码']),
        'supplyQty': _int(row['供货数量']),
        'inWhQty': _int(row['已入待检仓数量']),
        'reqArriveDate': _date(row['要求到货日期']),
    } for _, row in frames['notices'].iterrows()]

    payload['supplierConfigList'] = [{
        'supplierNo': _text(row['供应商编号']),
        'supplierName': _text(row['供应商名称']),
        'stockCycle': _number(row['备货周期（天）']),
        'transitTime': _number(row['物流在途时间（天）']),
        'overallScore': _number(row['综合评分']),
        'weekMaxCount': _int(row['每周最大到货次数'], 1),
        'monthMaxCount': _int(row['每月最大到货次数'], 999),
    } for _, row in frames['suppliers'].iterrows()]

    payload['whAreaConfigList'] = [{
        'whAreaId': index + 1,
        'whAreaName': _text(row['库区名称']),
        'whAreaType': '01' if _text(row['库区类型']) == '待检仓' else _text(row['库区类型']),
        'whAreaCap': _int(row['库区容量']),
        'inStockQty': _int(row['当前库存']),
        'arriveBatchQty': _int(row['每日最大接收批次数'], 999),
    } for index, (_, row) in enumerate(frames['areas'].iterrows())]

    payload['scheduleTimeList'] = [{
        'workDay': _date(row['工作日日期']),
        'startTime': _clock(row['开始时间']),
        'endTime': _clock(row['结束时间']),
    } for _, row in frames['workdays'].iterrows()]
    return payload


def validate_payload(payload: dict[str, Any]) -> list[str]:
    problems = []
    for set_name, (required, optional) in SPEC_FIELDS.items():
        rows = payload.get(set_name)
        if not isinstance(rows, list):
            problems.append(f'{set_name} 不是数组')
            continue
        for index, row in enumerate(rows):
            missing = required - set(row)
            extra = set(row) - required - optional
            if missing:
                problems.append(f'{set_name}[{index}] 缺必填字段: {sorted(missing)}')
            if extra:
                problems.append(f'{set_name}[{index}] 多余字段: {sorted(extra)}')
            for field, value in row.items():
                if field.lower().endswith(('id', 'no', 'code')) and isinstance(value, str) and value.endswith('.0'):
                    problems.append(f'{set_name}[{index}].{field} 出现 .0: {value}')
        if set_name == 'dmdPlanDetList':
            for index, row in enumerate(rows):
                if not isinstance(row.get('materialNoList'), list) or not row['materialNoList']:
                    problems.append(f'dmdPlanDetList[{index}].materialNoList 为空')
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description='到货排程 Excel 转 V0.0.6 JSON')
    parser.add_argument('--input', type=Path, default=Path('docs/样例/到货计划排程入参.xlsx'))
    parser.add_argument('--output', type=Path, default=Path('docs/报文/到货计划排程_请求示例_0825.xlsx转换.json'))
    args = parser.parse_args()
    payload = build_payload(args.input)
    problems = validate_payload(payload)
    if problems:
        raise ValueError('\n'.join(problems))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'已生成: {args.output}')
    for key, rows in payload.items():
        print(f'  {key}: {len(rows)} 条')
    print('注意: whAreaId 为转换器生成序号，正式口径需平台确认。')


if __name__ == '__main__':
    main()

