"""到货计划排程业务计算（8.24 算法基线）。

净需求、合同分配、月份拆分、日期规划和告警均在此业务层完成；writer
只负责把这些内部字段映射成 V0.0.6 出参字段。
"""
from __future__ import annotations

import logging
from collections import OrderedDict, defaultdict
from copy import deepcopy
from datetime import date, timedelta
from typing import Any

from .models import ArrivalResult, PreparedArrivalData

logger = logging.getLogger(__name__)


def _reference_maps(data: PreparedArrivalData):
    material_map: dict[str, dict[str, str]] = {}
    device_to_big: dict[str, str] = {}
    demand_by_material_month = defaultdict(lambda: defaultdict(int))
    for row in data.demands:
        material = row['material_no']
        if material not in material_map:
            material_map[material] = {
                'big_code': row['parent_equip_code'],
                'big_code_desc': row['equip_desc'],
                'equip_categ': row['equip_categ'],
                'equip_cls': row['equip_cls'],
            }
        device_to_big.setdefault(row['equip_code'], row['parent_equip_code'])
        demand_by_material_month[material][row['plan_ym']] += row['quantity']
    return material_map, device_to_big, demand_by_material_month


def build_net_demand_summary(data: PreparedArrivalData):
    """按物资编码+月份计算 8.24 净需求；仅首月抵扣全部供货和库存。"""
    material_map, device_to_big, demand_by_material_month = _reference_maps(data)

    qualified_raw = defaultdict(int)
    qualified_total = defaultdict(int)
    locked_total = defaultdict(int)
    safety_total = defaultdict(int)
    for row in data.qualified_stock:
        big = row['parent_equip_code'] or row['equip_code']
        qualified_raw[big] += row['qualified_qty'] - row['dist_lock_qty']
        qualified_total[big] += row['qualified_qty']
        locked_total[big] += row['dist_lock_qty']
        safety_total[big] += row['lower_limit_qty']

    unqualified = defaultdict(int)
    for row in data.unqualified_stock:
        big = device_to_big.get(row['equip_code'], row['equip_code'])
        unqualified[big] += row['unqualified_qty']

    supply_total = defaultdict(int)
    received_total = defaultdict(int)
    excluded_rows = []
    for row in data.supply_notices:
        material = row['material_no']
        supply_total[material] += row['supply_qty']
        received_total[material] += row['in_wh_qty']
        excluded_rows.append({
            'material_no': material,
            'supplier_no': row['supplier_no'],
            'supplier_name': row['supplier_name'],
            'required_arrive_date': row['required_arrive_date'],
            'supply_qty': row['supply_qty'],
            'in_wh_qty': row['in_wh_qty'],
        })

    net_demand: dict[str, dict[str, Any]] = {}
    summary_rows = []
    for material in sorted(demand_by_material_month):
        big = material_map.get(material, {}).get('big_code', '')
        # 按基线保留负值：负的可用合格品会反向增加净需求。
        net_qualified = qualified_raw.get(big, 0) - safety_total.get(big, 0)
        unqualified_qty = unqualified.get(big, 0)
        net_supply = max(0, supply_total.get(material, 0) - received_total.get(material, 0))
        month_values = {}
        for month_index, month in enumerate(sorted(demand_by_material_month[material])):
            demand_qty = demand_by_material_month[material][month]
            if month_index == 0:
                net_qty = demand_qty - net_supply - unqualified_qty - net_qualified
                shown = {
                    'supply_qty': supply_total.get(material, 0),
                    'in_wh_qty': received_total.get(material, 0),
                    'net_supply_qty': net_supply,
                    'unqualified_qty': unqualified_qty,
                    'lower_limit_qty': safety_total.get(big, 0),
                    'qualified_qty': qualified_total.get(big, 0),
                    'dist_lock_qty': locked_total.get(big, 0),
                    'net_qualified_qty': net_qualified,
                }
            else:
                net_qty = demand_qty
                shown = {key: 0 for key in (
                    'supply_qty', 'in_wh_qty', 'net_supply_qty', 'unqualified_qty',
                    'lower_limit_qty', 'qualified_qty', 'dist_lock_qty', 'net_qualified_qty',
                )}
            net_qty = max(0, net_qty)
            month_values[month] = {'total': demand_qty, 'net': net_qty}
            # 8.24 Excel 仅列出正净需求月份。
            if net_qty > 0:
                summary_rows.append({
                    'material_no': material,
                    'equip_code': big,
                    'plan_ym': month,
                    'demand_plan_qty': demand_qty,
                    **shown,
                    'net_demand_plan_qty': net_qty,
                })
        net_demand[material] = {
            'by_month': month_values,
            'total_demand': sum(value['total'] for value in month_values.values()),
            'total_net': sum(value['net'] for value in month_values.values()),
            'big_code': big,
        }
    logger.info('净需求计算完成：物资=%d，正净需求月份=%d', len(net_demand), len(summary_rows))
    return net_demand, summary_rows, excluded_rows, material_map


def _allocate_contracts(net_demand, data: PreparedArrivalData):
    supplier_info = {row['supplier_no']: row for row in data.suppliers}
    contracts_by_material = defaultdict(list)
    for source in data.contracts:
        row = deepcopy(source)
        row['uid'] = f"{row['supplier_no']}|{row['contract_detail_id']}|{row['material_no']}"
        contracts_by_material[row['material_no']].append(row)

    allocations = []
    shortages = []
    for material, net_info in net_demand.items():
        total_net = net_info['total_net']
        contracts = contracts_by_material.get(material, [])
        if not contracts:
            if total_net > 0:
                shortages.append({
                    'material_no': material,
                    'demand_qty': total_net,
                    'purchase_total_qty': 0,
                    'shortage_qty': total_net,
                    'alarm_date': data.workdays[0],
                })
                logger.warning('物资 %s 无对应合同，净需求缺口 %d', material, total_net)
            continue

        for contract in contracts:
            contract['remaining'] = max(0, contract['purchase_qty'] - contract['arrive_qty'])
            contract['progress'] = (
                contract['arrive_qty'] / contract['purchase_qty']
                if contract['purchase_qty'] > 0 else 1.0
            )
        total_remaining = sum(contract['remaining'] for contract in contracts)
        total_contract = sum(contract['purchase_qty'] for contract in contracts)
        total_arrived = sum(contract['arrive_qty'] for contract in contracts)
        overall_progress = total_arrived / total_contract if total_contract else 0
        if total_remaining < total_net:
            shortages.append({
                'material_no': material,
                'demand_qty': total_net,
                'purchase_total_qty': total_contract,
                'shortage_qty': total_net - total_remaining,
                'alarm_date': data.workdays[0],
            })
            logger.warning('物资 %s 合同剩余不足，缺口 %d', material, total_net - total_remaining)

        for contract in contracts:
            contract['proportion'] = contract['purchase_qty'] / total_contract if total_contract else 0
        allocatable = min(total_net, total_remaining)
        remaining = allocatable
        contracts.sort(key=lambda contract: (
            contract['progress'],
            -supplier_info.get(contract['supplier_no'], {}).get('overall_score', 0),
        ))
        quantities: dict[str, int] = {}

        # 第一阶段：优先补齐执行进度较低的合同。
        for contract in contracts:
            if remaining <= 0:
                break
            target = int(contract['purchase_qty'] * overall_progress)
            gap = min(max(0, target - contract['arrive_qty']), contract['remaining'])
            quantity = min(gap, remaining)
            if quantity > 0:
                quantities[contract['uid']] = quantity
                remaining -= quantity

        # 第二阶段：按合同量占比分配；沿用 8.24 的 allocatable 基数。
        if remaining > 0:
            for index, contract in enumerate(contracts):
                if remaining <= 0:
                    break
                allocated = quantities.get(contract['uid'], 0)
                available = contract['remaining'] - allocated
                if available <= 0:
                    continue
                if index == len(contracts) - 1:
                    quantity = min(remaining, available)
                else:
                    quantity = min(int(allocatable * contract['proportion']), available, remaining)
                if quantity > 0:
                    quantities[contract['uid']] = allocated + quantity
                    remaining -= quantity

        # 第三阶段：处理整数截断余量。
        if remaining > 0:
            for contract in contracts:
                if remaining <= 0:
                    break
                allocated = quantities.get(contract['uid'], 0)
                quantity = min(remaining, contract['remaining'] - allocated)
                if quantity > 0:
                    quantities[contract['uid']] = allocated + quantity
                    remaining -= quantity

        for contract in contracts:
            quantity = quantities.get(contract['uid'], 0)
            if quantity <= 0:
                continue
            allocations.append({
                'uid': contract['uid'],
                'material_no': material,
                'contract_id': contract['contract_id'],
                'contract_detail_id': contract['contract_detail_id'],
                'supplier_no': contract['supplier_no'],
                'supplier_name': contract['supplier_name'],
                'purchase_qty': contract['purchase_qty'],
                'arrive_qty': contract['arrive_qty'],
                'execution_progress': round(contract['progress'] * 100, 2),
                'contract_ratio': round(contract['proportion'] * 100, 2),
                'same_material_total_progress': round(overall_progress * 100, 2),
                'allocation_qty': quantity,
                'after_allocation_progress': round(
                    (contract['arrive_qty'] + quantity) / contract['purchase_qty'] * 100, 2
                ) if contract['purchase_qty'] else 0,
                'remaining_contract_qty': contract['remaining'] - quantity,
                'supplier_score': supplier_info.get(contract['supplier_no'], {}).get('overall_score', 0),
            })
    logger.info('合同分配完成：分配=%d，不足告警=%d', len(allocations), len(shortages))
    return allocations, shortages


def _split_allocations_by_month(allocations, summary_rows):
    month_net = {(row['material_no'], row['plan_ym']): row['net_demand_plan_qty'] for row in summary_rows}
    result = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for allocation in allocations:
        material = allocation['material_no']
        months = {month: qty for (mat, month), qty in month_net.items() if mat == material}
        total = sum(months.values())
        if total <= 0:
            continue
        ordered_months = sorted(months)
        exact = {month: allocation['allocation_qty'] * months[month] / total for month in ordered_months}
        integer = {month: int(value) for month, value in exact.items()}
        remainder = allocation['allocation_qty'] - sum(integer.values())
        fractions = sorted(
            ((exact[month] - integer[month], month) for month in ordered_months),
            reverse=True,
        )
        for index in range(remainder):
            integer[fractions[index][1]] += 1
        for month, quantity in integer.items():
            if quantity > 0:
                result[month][allocation['supplier_no']][allocation['uid']] += quantity
    return result


def _build_schedule(data, allocations, summary_rows, material_map, excluded_dates):
    suppliers = {row['supplier_no']: row for row in data.suppliers}
    uid_map = {row['uid']: row for row in allocations}
    uid_to_big = {uid: material_map.get(row['material_no'], {}).get('big_code', '') for uid, row in uid_map.items()}
    by_month = _split_allocations_by_month(allocations, summary_rows)
    months = OrderedDict()
    for workday in data.workdays:
        months.setdefault((workday.year, workday.month), []).append(workday)

    pending_areas = [area for area in data.warehouse_areas if area['warehouse_area_type'] in ('01', '待检仓')]
    daily_max = pending_areas[0]['daily_batch_limit'] if pending_areas else 3
    algo_start = data.workdays[0]
    daily_used = defaultdict(int)
    weekly_used = defaultdict(int)
    schedule_rows = []

    for month_key in sorted(months):
        month = f'{month_key[0]}{month_key[1]:02d}'
        available_workdays = [day for day in months[month_key] if day not in excluded_dates]
        if not available_workdays:
            logger.warning('%s 所有工作日均为供货通知排除日期，无法排程', month)
            continue
        month_allocations = by_month.get(month, {})
        if not month_allocations:
            continue

        all_batches = []
        for supplier_no, uid_quantities in month_allocations.items():
            supplier = suppliers.get(supplier_no)
            if not supplier:
                logger.warning('供应商 %s 无 supplierConfigList 配置，跳过排程', supplier_no)
                continue
            weekly_max = supplier['week_max_count']
            monthly_max = supplier['month_max_count']
            stock_cycle = int(supplier['stock_cycle'])
            transit_time = int(supplier['transit_time'])
            lead_time = stock_cycle + transit_time
            earliest = algo_start + timedelta(days=lead_time)
            supplier_days = [day for day in available_workdays if day >= earliest] or [available_workdays[-1]]
            supplier_weeks = OrderedDict()
            for day in supplier_days:
                supplier_weeks.setdefault(day.isocalendar()[:2], []).append(day)
            week_keys = list(supplier_weeks)

            quantities_by_big = defaultdict(dict)
            for uid, quantity in uid_quantities.items():
                big = uid_to_big.get(uid, '')
                if big:
                    quantities_by_big[big][uid] = quantity

            for big, uid_quantity in quantities_by_big.items():
                total_quantity = sum(uid_quantity.values())
                if total_quantity <= 0:
                    continue
                batch_count = max(1, min(weekly_max * len(week_keys), monthly_max, total_quantity))
                base_quantity, remainder_quantity = divmod(total_quantity, batch_count)
                batches_per_week = [0] * len(week_keys)
                remaining_batches = batch_count
                for week_index in range(len(week_keys)):
                    if remaining_batches <= 0:
                        break
                    count = min(weekly_max, remaining_batches)
                    batches_per_week[week_index] = count
                    remaining_batches -= count

                batch_index = 0
                remaining_by_uid = dict(uid_quantity)
                for week_index, count in enumerate(batches_per_week):
                    if count <= 0:
                        continue
                    week_days = supplier_weeks[week_keys[week_index]]
                    for within_week_index in range(count):
                        day_index = min(int(within_week_index * len(week_days) / count), len(week_days) - 1)
                        planned_date = week_days[day_index]
                        batch_quantity = base_quantity + (1 if batch_index < remainder_quantity else 0)
                        batch_index += 1
                        current_remaining = sum(remaining_by_uid.values())
                        batch_quantity = min(batch_quantity, current_remaining)
                        if batch_quantity <= 0:
                            continue
                        detail_allocation = {}
                        detail_remaining = batch_quantity
                        detail_items = list(remaining_by_uid.items())
                        for item_index, (uid, quantity) in enumerate(detail_items):
                            if detail_remaining <= 0 or quantity <= 0:
                                continue
                            if item_index == len(detail_items) - 1:
                                assigned = min(detail_remaining, quantity)
                            else:
                                assigned = max(1, int(batch_quantity * quantity / current_remaining))
                                assigned = min(assigned, detail_remaining, quantity)
                            if assigned > 0:
                                detail_allocation[uid] = assigned
                                detail_remaining -= assigned
                                remaining_by_uid[uid] = quantity - assigned
                        if detail_allocation:
                            all_batches.append({
                                'supplier_no': supplier_no,
                                'supplier': supplier,
                                'date': planned_date,
                                'batch_quantity': batch_quantity,
                                'detail_allocation': detail_allocation,
                                'big_code': big,
                                'stock_cycle': stock_cycle,
                                'transit_time': transit_time,
                            })

        # 消解首尾残缺周的日容量超载，规则与 8.24 基线一致。
        week_of_date = {day: day.isocalendar()[:2] for day in available_workdays}
        week_capacity = defaultdict(int)
        for day in available_workdays:
            week_capacity[week_of_date[day]] += daily_max
        for _ in range(200):
            week_batches = defaultdict(list)
            for batch in all_batches:
                week_batches[week_of_date[batch['date']]].append(batch)
            overloaded = [
                (week, len(batches)) for week, batches in week_batches.items()
                if len(batches) > week_capacity.get(week, 0)
            ]
            if not overloaded:
                break
            overloaded.sort(key=lambda item: -item[1])
            week = overloaded[0][0]
            merged = False
            for batch in sorted(week_batches[week], key=lambda item: item['date']):
                targets = [other for other in all_batches if (
                    other is not batch
                    and other['supplier_no'] == batch['supplier_no']
                    and other['big_code'] == batch['big_code']
                    and week_of_date[other['date']] != week
                )]
                targets.sort(key=lambda other: (
                    week_capacity.get(week_of_date[other['date']], 0)
                    - len(week_batches.get(week_of_date[other['date']], []))
                ), reverse=True)
                for target in targets:
                    target_week = week_of_date[target['date']]
                    if len(week_batches.get(target_week, [])) >= week_capacity.get(target_week, 0):
                        continue
                    target['batch_quantity'] += batch['batch_quantity']
                    for uid, quantity in batch['detail_allocation'].items():
                        target['detail_allocation'][uid] = target['detail_allocation'].get(uid, 0) + quantity
                    all_batches.remove(batch)
                    merged = True
                    break
                if merged:
                    break
            if not merged:
                break

        all_batches.sort(key=lambda item: item['date'])
        placed_batches = []
        for batch in all_batches:
            supplier_no = batch['supplier_no']
            big = batch['big_code']
            weekly_max = suppliers[supplier_no]['week_max_count']
            earliest = batch['date']
            placed = False
            for day in available_workdays:
                if day < earliest or daily_used[day] >= daily_max:
                    continue
                week = day.isocalendar()[:2]
                if weekly_used[(supplier_no, big, week)] >= weekly_max:
                    continue
                batch['date'] = day
                daily_used[day] += 1
                weekly_used[(supplier_no, big, week)] += 1
                placed = True
                break
            if not placed:
                # 频次已满时合并到本月相同供应商+大码的已排批次，不新增到货次数。
                targets = [other for other in placed_batches if (
                    other['supplier_no'] == supplier_no
                    and other['big_code'] == big
                    and other['date'] >= earliest
                )]
                if targets:
                    target = targets[-1]
                    target['batch_quantity'] += batch['batch_quantity']
                    for uid, quantity in batch['detail_allocation'].items():
                        target['detail_allocation'][uid] = target['detail_allocation'].get(uid, 0) + quantity
                    batch['_drop'] = True
                    placed = True
            if not placed:
                day = available_workdays[-1]
                batch['date'] = day
                daily_used[day] += 1
                weekly_used[(supplier_no, big, day.isocalendar()[:2])] += 1
                logger.warning('%s 无法同时满足日容量与频次限制，批次回落到 %s', month, day)
            if not batch.get('_drop'):
                placed_batches.append(batch)

        all_batches = [batch for batch in all_batches if not batch.get('_drop')]

        # 同供应商同日合并成同一批次；明细仍按合同输出。
        grouped = defaultdict(list)
        for batch in all_batches:
            grouped[(batch['date'], batch['supplier_no'])].append(batch)
        for batches in grouped.values():
            main = batches[0]
            for batch in batches[1:]:
                main['batch_quantity'] += batch['batch_quantity']
                for uid, quantity in batch['detail_allocation'].items():
                    main['detail_allocation'][uid] = main['detail_allocation'].get(uid, 0) + quantity
                all_batches.remove(batch)

        batch_counter = defaultdict(int)
        for batch in all_batches:
            supplier_no = batch['supplier_no']
            supplier = batch['supplier']
            arrival_date = batch['date']
            batch_counter[(supplier_no, month)] += 1
            batch_no = f"{supplier_no}-{month}-{batch_counter[(supplier_no, month)]}"
            for uid, quantity in batch['detail_allocation'].items():
                if quantity <= 0:
                    continue
                allocation = uid_map[uid]
                mapping = material_map.get(allocation['material_no'], {})
                schedule_rows.append({
                    'arrival_plan_date': arrival_date,
                    'plan_ym': month,
                    'plan_week': f'{arrival_date.isocalendar()[0]}-W{arrival_date.isocalendar()[1]:02d}',
                    'equip_categ': mapping.get('equip_categ', ''),
                    'equip_cls': mapping.get('equip_cls', ''),
                    'material_no': allocation['material_no'],
                    'equip_code': mapping.get('big_code', ''),
                    'equip_desc': mapping.get('big_code_desc', ''),
                    'supplier_no': supplier_no,
                    'contract_id': allocation['contract_id'],
                    'contract_detail_id': allocation['contract_detail_id'],
                    'plan_qty': quantity,
                    'stock_cycle': supplier['stock_cycle'],
                    'transit_time': supplier['transit_time'],
                    '_batch_no': batch_no,
                    '_big_code': mapping.get('big_code', ''),
                })
                logger.debug('到货批次 %s：%s / %s / %d', batch_no, allocation['material_no'], arrival_date, quantity)

    schedule_rows.sort(key=lambda row: (row['arrival_plan_date'], row['supplier_no']))
    return schedule_rows, daily_max


def _build_alerts(data, schedule_rows, daily_max):
    daily_quantity = defaultdict(int)
    daily_batch_numbers = defaultdict(set)
    daily_line_count = defaultdict(int)
    for row in schedule_rows:
        day = row['arrival_plan_date']
        daily_quantity[day] += row['plan_qty']
        daily_batch_numbers[day].add(row['_batch_no'])
        daily_line_count[day] += 1
    daily_batch_count = {day: len(numbers) for day, numbers in daily_batch_numbers.items()}

    capacity_alarms = []
    daily_batch_alarms = []
    pending_areas = [area for area in data.warehouse_areas if area['warehouse_area_type'] in ('01', '待检仓')]
    for area in pending_areas:
        current_stock = area['current_stock']
        for workday in data.workdays:
            arrival = daily_quantity.get(workday, 0)
            current_stock += arrival
            if current_stock > area['capacity']:
                capacity_alarms.append({
                    'warehouse_area_id': area['warehouse_area_id'],
                    'warehouse_area_name': area['warehouse_area_name'],
                    'alarm_date': workday,
                    'in_stock_qty': current_stock,
                    'warehouse_area_capacity': area['capacity'],
                    'over_capacity_qty': current_stock - area['capacity'],
                    'day_arrive_qty': arrival,
                    'day_batch_qty': daily_batch_count.get(workday, 0),
                })
                logger.warning('库区 %s 在 %s 超容 %d', area['warehouse_area_name'], workday, current_stock - area['capacity'])
            batch_count = daily_batch_count.get(workday, 0)
            line_count = daily_line_count.get(workday, 0)
            if batch_count > area['daily_batch_limit'] or line_count > area['daily_batch_limit']:
                daily_batch_alarms.append({
                    'warehouse_area_id': area['warehouse_area_id'],
                    'warehouse_area_name': area['warehouse_area_name'],
                    'alarm_date': workday,
                    'day_batch_qty': batch_count,
                    'day_line_qty': line_count,
                    'daily_batch_limit': area['daily_batch_limit'],
                    'day_arrive_qty': arrival,
                })
                logger.warning('库区 %s 在 %s 批次/明细超限', area['warehouse_area_name'], workday)
    return capacity_alarms, daily_batch_alarms


def run_scheduling(data: PreparedArrivalData) -> ArrivalResult:
    net_demand, summary_rows, excluded_rows, material_map = build_net_demand_summary(data)
    allocations, shortages = _allocate_contracts(net_demand, data)
    excluded_dates = {row['required_arrive_date'] for row in excluded_rows if row['required_arrive_date']}
    schedule_rows, daily_max = _build_schedule(
        data, allocations, summary_rows, material_map, excluded_dates,
    )
    capacity_alarms, daily_batch_alarms = _build_alerts(data, schedule_rows, daily_max)
    return ArrivalResult(
        schedule_rows=schedule_rows,
        capacity_alarm_rows=capacity_alarms,
        contract_allocation_rows=allocations,
        contract_shortage_rows=shortages,
        net_demand_rows=summary_rows,
        daily_batch_alert_rows=daily_batch_alarms,
        excluded_notice_rows=excluded_rows,
    )
