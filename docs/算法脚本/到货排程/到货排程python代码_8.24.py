import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict, OrderedDict
import math
import os

# ============================================================
# 1. 读取输入数据
# ============================================================
file_path = r"C:\Users\H5966\Desktop\到货排程\到货计划排程入参-20260821(1).xlsx"

dfs = {}

dfs['demand'] = pd.read_excel(file_path, sheet_name='月度需用',
    converters={
        '物资编码': str, '设备类型码': str, '设备类型码大码': str,
        '设备类别': str, '设备分类': str,
    })
dfs['qualified'] = pd.read_excel(file_path, sheet_name='合格品库存详情（立库+成品仓）',
    converters={'设备类型码': str, '设备类型码大码': str})
dfs['unqualified'] = pd.read_excel(file_path, sheet_name='非合格品库存详情（待检仓+立库）',
    converters={'设备类型码': str})
dfs['contracts'] = pd.read_excel(file_path, sheet_name='订单合同清单',
    converters={'物资编码': str, '设备类别': str, '设备分类': str})
dfs['notified'] = pd.read_excel(file_path, sheet_name='已供货通知物资',
    converters={'物资编码': str, '设备类型码': str})
dfs['supplier'] = pd.read_excel(file_path, sheet_name='供应商信息',
    converters={'供应商编号': str})
dfs['capacity'] = pd.read_excel(file_path, sheet_name='库区容量')
dfs['time_config'] = pd.read_excel(file_path, sheet_name='库房排程时间')


def clean_columns(df):
    df.columns = df.columns.str.strip()
    return df


for key in dfs:
    dfs[key] = clean_columns(dfs[key])

# ============================================================
# 2. 解析库房排程时间（工作日配置）
# ============================================================
workdays = set()
for _, row in dfs['time_config'].iterrows():
    d = row['工作日日期']
    if isinstance(d, datetime):
        workdays.add(d.date())
    elif isinstance(d, str):
        workdays.add(datetime.strptime(d, '%Y-%m-%d').date())
    else:
        base = datetime(1899, 12, 30)
        workdays.add((base + timedelta(days=int(d))).date())

workdays = sorted(workdays)
print(f"工作日数量: {len(workdays)}, 范围: {workdays[0]} ~ {workdays[-1]}")

weeks = OrderedDict()
months = OrderedDict()
for wd in workdays:
    wk = wd.isocalendar()[:2]
    mk = (wd.year, wd.month)
    if wk not in weeks:
        weeks[wk] = []
    weeks[wk].append(wd)
    if mk not in months:
        months[mk] = []
    months[mk].append(wd)

month_keys = sorted(months.keys())
print(f"月份: {['{}-{:02d}'.format(*mk) for mk in month_keys]}")
for mk in month_keys:
    print(f"  {mk[0]}-{mk[1]:02d}: {len(months[mk])}个工作日, {months[mk][0]} ~ {months[mk][-1]}")

# ============================================================
# 3. 解析供应商信息
# ============================================================
supplier_info = {}
for _, row in dfs['supplier'].iterrows():
    sid = str(row['供应商编号'])
    supplier_info[sid] = {
        'name': str(row['供应商名称']),
        'timely_rate': float(row['到货及时率']) if pd.notna(row['到货及时率']) else 0,
        'quality_rate': float(row['设备合格率']) if pd.notna(row['设备合格率']) else 0,
        'prep_days': int(row['备货周期（天）']) if pd.notna(row['备货周期（天）']) else 0,
        'transit_days': int(row['物流在途时间（天）']) if pd.notna(row['物流在途时间（天）']) else 0,
        'rating': float(row['综合评分']) if pd.notna(row['综合评分']) else 0,
        'weekly_max': int(row['同设备类型码每周最大到货次数']) if pd.notna(row['同设备类型码每周最大到货次数']) else 1,
        'monthly_max': int(row['同设备类型码每月最大到货次数']) if pd.notna(row['同设备类型码每月最大到货次数']) else 999,
    }

# ============================================================
# 4. 解析已供货通知物资：排除日期 + 供货数量/已入待检仓数量
# ============================================================
notified_dates = set()
notified_date_details = []
supply_by_mat = defaultdict(int)      # 供货数量（按物资编码）
received_by_mat = defaultdict(int)    # 已入待检仓数量（按物资编码）

for _, row in dfs['notified'].iterrows():
    mat_code = str(row['物资编码'])
    supply = int(row['供货数量']) if pd.notna(row['供货数量']) else 0
    received = int(row['已入待检仓数量']) if pd.notna(row['已入待检仓数量']) else 0
    supply_by_mat[mat_code] += supply
    received_by_mat[mat_code] += received

    d = row['要求到货日期']
    if pd.notna(d):
        if isinstance(d, datetime):
            dt = d.date()
        elif isinstance(d, str):
            dt = datetime.strptime(d, '%Y-%m-%d').date()
        else:
            continue
        notified_dates.add(dt)
        notified_date_details.append({
            '物资编码': mat_code,
            '供应商编号': str(row['供应商编号']),
            '供应商名称': str(row['供应商名称']),
            '要求到货日期': dt,
            '供货数量': supply,
            '已入待检仓数量': received,
        })

print(f"\n已供货通知排除日期: {sorted(notified_dates)}")

# ============================================================
# 5. 需求1: 净需求计算
#    甲方20260824优化点：正确的净需求公式
#    净需求 = 需求 - (供货数量 - 已入待检仓数量) - 非合格在库库存
#               - (合格在库库存 - 未配送库存 - 安全库存)
#    首月抵扣全部库存/供货，后续月抵扣为0（保留原月份拆分规则）
# ============================================================
# 5.1 物资编码 → 设备类型码大码、设备分类等映射
material_map = {}
dev_code_to_big = {}
for _, row in dfs['demand'].iterrows():
    mat_code = str(row['物资编码'])
    dev_code = str(row['设备类型码'])
    big_code = str(row['设备类型码大码'])
    if mat_code not in material_map:
        material_map[mat_code] = {
            'big_code': big_code,
            'big_code_desc': str(row['设备类型码大码描述']) if pd.notna(row['设备类型码大码描述']) else '',
            'dev_category': str(row['设备分类']) if pd.notna(row['设备分类']) else '',
            'dev_category_name': str(row['设备分类名称']) if pd.notna(row['设备分类名称']) else '',
            'dev_type': str(row['设备类别']) if pd.notna(row['设备类别']) else '',
            'dev_type_name': str(row['设备类别名称']) if pd.notna(row['设备类别名称']) else '',
        }
    if dev_code not in dev_code_to_big:
        dev_code_to_big[dev_code] = big_code

# 5.2 月度需用汇总（按物资编码 + 月份）
demand_by_mat_month = defaultdict(lambda: defaultdict(int))
for _, row in dfs['demand'].iterrows():
    mat_code = str(row['物资编码'])
    month = str(row['所属月份'])
    qty = int(row['计划数量'])
    demand_by_mat_month[mat_code][month] += qty

# 5.3 合格品库存（合格在库 - 未配送）与安全库存（按设备类型码大码）
qualified_raw = defaultdict(int)          # 合格在库 - 未配送（可负）
qualified_stock_total = defaultdict(int)  # 合格在库合计
undelivered_total = defaultdict(int)      # 未配送合计
safety_stock = defaultdict(int)           # 安全库存合计
for _, row in dfs['qualified'].iterrows():
    stock = int(row['合格在库库存']) if pd.notna(row['合格在库库存']) else 0
    undelivered = int(row['未配送库存']) if pd.notna(row['未配送库存']) else 0
    safety = int(row['安全库存']) if pd.notna(row['安全库存']) else 0
    big_code = str(row['设备类型码大码'])
    if big_code and big_code != 'nan':
        qualified_raw[big_code] += stock - undelivered
        qualified_stock_total[big_code] += stock
        undelivered_total[big_code] += undelivered
        safety_stock[big_code] += safety

# 5.4 非合格品库存（按设备类型码大码）
unqualified_avail = defaultdict(int)
for _, row in dfs['unqualified'].iterrows():
    dev_code = str(row['设备类型码'])
    qty = int(row['非合格在库库存']) if pd.notna(row['非合格在库库存']) else 0
    big_code = dev_code_to_big.get(dev_code, dev_code)
    unqualified_avail[big_code] += qty

# 5.5 已供货通知净供货（供货数量 - 已入待检仓数量）
all_mat_codes = set(demand_by_mat_month.keys())
supply_pending = {}
for mat_code in all_mat_codes:
    supply_pending[mat_code] = max(0, supply_by_mat.get(mat_code, 0) - received_by_mat.get(mat_code, 0))

# 5.6 计算净需求（按物资编码 + 月份）
net_demand = {}
net_demand_rows = []

for mat_code in sorted(all_mat_codes):
    big_code = material_map.get(mat_code, {}).get('big_code', '')
    q_avail = qualified_raw.get(big_code, 0) - safety_stock.get(big_code, 0)   # 合格在库-未配送-安全库存（可负）
    u_avail = unqualified_avail.get(big_code, 0)                                # 非合格在库（非负）
    s_pending = supply_pending.get(mat_code, 0)                                 # 供货-已入待检（非负）

    month_demand = dict(demand_by_mat_month[mat_code])
    months_for_mat = sorted(month_demand.keys())

    net_by_month = {}
    for mi, month in enumerate(months_for_mat):
        m_demand = month_demand[month]
        if mi == 0:
            # 首月：抵扣全部供货/库存/安全库存
            net = m_demand - s_pending - u_avail - q_avail
            s_use, u_use = s_pending, u_avail
            show_supply = supply_by_mat.get(mat_code, 0)
            show_received = received_by_mat.get(mat_code, 0)
            show_stock = qualified_stock_total.get(big_code, 0)
            show_undelivered = undelivered_total.get(big_code, 0)
            show_safety = safety_stock.get(big_code, 0)
        else:
            # 后续月：抵扣为0
            net = m_demand
            s_use, u_use = 0, 0
            show_supply = show_received = 0
            show_stock = show_undelivered = show_safety = 0

        net = max(0, net)

        net_by_month[month] = {
            'total': m_demand,
            'net': net,
        }

        if net > 0:
            net_demand_rows.append({
                '物资编码': mat_code,
                '月份': month,
                '总需求': m_demand,
                '供货数量': show_supply,
                '已入待检仓数量': show_received,
                '供货净抵扣': s_use,
                '非合格在库库存': u_use,
                '合格在库库存': show_stock,
                '未配送库存': show_undelivered,
                '安全库存': show_safety,
                '净需求': net,
            })

    net_demand[mat_code] = {
        'by_month': net_by_month,
        'total_demand': sum(month_demand.values()),
        'total_net': sum(v['net'] for v in net_by_month.values()),
        'big_code': big_code,
    }

print(f"\n=== 净需求汇总 ({len(net_demand)} 个物资编码) ===")
for mc, nd in sorted(net_demand.items()):
    for month, mn in sorted(nd['by_month'].items()):
        print(f"  {mc} [{month}]: 总需求={mn['total']}, 净需求={mn['net']}")

# ============================================================
# 6. 合同分配（按物资编码）
#    用 (供应商编号|合同明细标识|物资编码) 作为唯一内部键，避免
#    同一供应商下合同明细标识重复导致的多物资分配串号
# ============================================================
contracts_by_mat = defaultdict(list)
for _, row in dfs['contracts'].iterrows():
    mat_code = str(row['物资编码'])
    sid = str(row['供应商编号'])
    detail_id = str(row['合同明细标识'])
    uid = f"{sid}|{detail_id}|{mat_code}"
    contracts_by_mat[mat_code].append({
        'uid': uid,
        'detail_id': detail_id,
        'contract_id': str(row['合同标识']),
        'mat_code': mat_code,
        'mat_name': str(row.get('物资编码名称', '')),
        'dev_type': str(row.get('设备类别', '')),
        'dev_type_name': str(row.get('设备类别名称', '')),
        'dev_category': str(row.get('设备分类', '')),
        'dev_category_name': str(row.get('设备分类名称', '')),
        'contract_qty': int(row['合同数量']),
        'arrived_qty': int(row['已到货数量']),
        'supplier_id': sid,
        'supplier_name': str(row['供应商名称']),
    })

contract_allocation = []
contract_shortage = []

for mat_code, nd_info in net_demand.items():
    total_net = nd_info['total_net']
    contracts = contracts_by_mat.get(mat_code, [])

    if not contracts:
        if total_net > 0:
            contract_shortage.append({
                '物资编码': mat_code, '净需求': total_net, '合同总量': 0,
                '缺口数量': total_net, '说明': '无对应合同'
            })
        continue

    for c in contracts:
        c['remaining'] = max(0, c['contract_qty'] - c['arrived_qty'])
        c['progress'] = c['arrived_qty'] / c['contract_qty'] if c['contract_qty'] > 0 else 1.0

    total_remaining = sum(c['remaining'] for c in contracts)
    total_contract = sum(c['contract_qty'] for c in contracts)
    total_arrived = sum(c['arrived_qty'] for c in contracts)

    overall_progress = total_arrived / total_contract if total_contract > 0 else 0

    if total_remaining < total_net:
        contract_shortage.append({
            '物资编码': mat_code, '净需求': total_net,
            '合同总量': total_contract, '合同剩余': total_remaining,
            '缺口数量': total_net - total_remaining, '说明': '合同剩余量不足'
        })

    for c in contracts:
        c['proportion'] = c['contract_qty'] / total_contract if total_contract > 0 else 0

    allocatable = min(total_net, total_remaining)
    remaining_alloc = allocatable

    contracts.sort(key=lambda c: (
        c['progress'],
        -supplier_info.get(c['supplier_id'], {}).get('rating', 0)
    ))

    phase1_allocations = {}

    for c in contracts:
        if remaining_alloc <= 0:
            break
        target_arrived = int(c['contract_qty'] * overall_progress)
        shortage_to_target = max(0, target_arrived - c['arrived_qty'])
        shortage_to_target = min(shortage_to_target, c['remaining'])
        alloc = min(shortage_to_target, remaining_alloc)
        if alloc > 0:
            phase1_allocations[c['uid']] = alloc
            remaining_alloc -= alloc

    if remaining_alloc > 0:
        for idx, c in enumerate(contracts):
            if remaining_alloc <= 0:
                break
            already_alloc = phase1_allocations.get(c['uid'], 0)
            still_available = c['remaining'] - already_alloc
            if still_available <= 0:
                continue
            if idx == len(contracts) - 1:
                alloc = min(remaining_alloc, still_available)
            else:
                alloc = min(int(allocatable * c['proportion']), still_available, remaining_alloc)
            if alloc > 0:
                phase1_allocations[c['uid']] = already_alloc + alloc
                remaining_alloc -= alloc

    if remaining_alloc > 0:
        for c in contracts:
            if remaining_alloc <= 0:
                break
            already_alloc = phase1_allocations.get(c['uid'], 0)
            still_available = c['remaining'] - already_alloc
            extra = min(remaining_alloc, still_available)
            if extra > 0:
                phase1_allocations[c['uid']] = already_alloc + extra
                remaining_alloc -= extra

    for c in contracts:
        alloc_qty = phase1_allocations.get(c['uid'], 0)
        if alloc_qty > 0:
            new_progress = (c['arrived_qty'] + alloc_qty) / c['contract_qty'] * 100 if c['contract_qty'] > 0 else 0
            contract_allocation.append({
                'uid': c['uid'],
                '物资编码': mat_code,
                '合同标识': c['contract_id'],
                '合同明细标识': c['detail_id'],
                '供应商编号': c['supplier_id'],
                '供应商名称': c['supplier_name'],
                '合同数量': c['contract_qty'],
                '已到货数量': c['arrived_qty'],
                '执行进度(%)': round(c['progress'] * 100, 2),
                '合同占比(%)': round(c['proportion'] * 100, 2),
                '同物资总进度(%)': round(overall_progress * 100, 2),
                '本次分配数量': alloc_qty,
                '分配后进度(%)': round(new_progress, 2),
                '分配后剩余合同量': c['remaining'] - alloc_qty,
                '供应商评分': supplier_info.get(c['supplier_id'], {}).get('rating', 0),
            })

total_alloc = sum(a['本次分配数量'] for a in contract_allocation)
print(f"\n=== 合同分配结果: {len(contract_allocation)} 条, 总分配量={total_alloc} ===")

# 分配明细 → 物资/大码 的唯一映射（供后续排程使用）
uid_map = {a['uid']: a for a in contract_allocation}
uid_to_big = {a['uid']: material_map.get(a['物资编码'], {}).get('big_code', '') for a in contract_allocation}

# ============================================================
# 7. 按月份规划到货日期
#    需求2: 按月份分开规划，当月需求当月满足
#    需求3+4: 每日批次数不超过待检仓每日最大接收批次数
#    需求5: 排除已供货通知的到货日期
#    甲方20260824优化点：同设备类型码每周/每月最大到货次数按
#      (供应商 + 设备类型码大码) 维度限制，而非供应商整体
# ============================================================
algo_start_date = workdays[0]
print(f"\n算法起始日期: {algo_start_date}")

daily_max_batches = 3
for _, row in dfs['capacity'].iterrows():
    if str(row['库区类型']) == '待检仓':
        daily_max_batches = int(row['每日最大接收批次数']) if pd.notna(row['每日最大接收批次数']) else 999
        break

print(f"待检仓每日最大接收批次数: {daily_max_batches}")

# 7.1 按物资编码 + 月份拆分净需求，确定每个合同分配对应的月份
mat_month_net = {}
for row in net_demand_rows:
    key = (row['物资编码'], row['月份'])
    mat_month_net[key] = row['净需求']

contract_alloc_by_month = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

for a in contract_allocation:
    mat_code = a['物资编码']
    uid = a['uid']
    sid = a['供应商编号']
    alloc_qty = a['本次分配数量']

    month_nets = {}
    for (mc, month), net in mat_month_net.items():
        if mc == mat_code:
            month_nets[month] = net

    total_month_net = sum(month_nets.values())
    if total_month_net <= 0:
        continue

    sorted_months_for_mat = sorted(month_nets.keys())
    # 使用最大余数法分配，避免整数截断导致前期月份少分
    exact_allocs = {month: alloc_qty * month_nets[month] / total_month_net for month in sorted_months_for_mat}
    int_allocs = {m: int(v) for m, v in exact_allocs.items()}
    remainder = alloc_qty - sum(int_allocs.values())
    fracs = sorted([(exact_allocs[m] - int_allocs[m], m) for m in sorted_months_for_mat], reverse=True)
    for i in range(remainder):
        int_allocs[fracs[i][1]] += 1
    for month in sorted_months_for_mat:
        month_alloc = int_allocs[month]
        if month_alloc > 0:
            contract_alloc_by_month[month][sid][uid] += month_alloc

total_month_alloc = sum(
    qty for month_data in contract_alloc_by_month.values()
    for sid_data in month_data.values()
    for qty in sid_data.values()
)
print(f"月份分配总量验证: {total_month_alloc} (应为{total_alloc})")

# 7.2 按月份规划到货
daily_arrival_plan = []
batch_seq = defaultdict(int)

# 每日/每周占用需跨月份累计：边界月（本数据 3月/4月 共享 ISO 第14周）时，
# 若在每个月内重置计数，会让同(供应商,设备类型码大码)在边界周被排两次而超限。
# 【甲方20260824问题2跨月修复】
daily_used = defaultdict(int)       # 每日已占批次数（跨月累计）
weekly_used = defaultdict(int)      # (供应商,大码,ISO周) 已占批次数（跨月累计）

for month_key in month_keys:
    month_str = f"{month_key[0]}{month_key[1]:02d}"
    month_workdays = months[month_key]

    if month_key not in months or not months[month_key]:
        continue

    available_workdays = [wd for wd in month_workdays if wd not in notified_dates]
    if not available_workdays:
        print(f"  {month_str}: 所有工作日均为已通知日期，无法排程")
        continue

    month_allocations = contract_alloc_by_month.get(month_str, {})
    if not month_allocations:
        continue

    month_weeks = OrderedDict()
    for wd in available_workdays:
        wk = wd.isocalendar()[:2]
        if wk not in month_weeks:
            month_weeks[wk] = []
        month_weeks[wk].append(wd)

    daily_slot_used = defaultdict(int)

    # 收集该月所有设备类型码大码，检查是否超过可用槽位
    month_dev_big_codes = set()
    for sid, uid_quantities in month_allocations.items():
        for uid in uid_quantities:
            big_code = uid_to_big.get(uid, '')
            if big_code:
                month_dev_big_codes.add(big_code)

    available_slots = len(available_workdays) * daily_max_batches
    if len(month_dev_big_codes) > available_slots:
        print(f"  ⚠ {month_str}: 设备类型码种类({len(month_dev_big_codes)})超过可用槽位({available_slots})，无法规划！")
        continue

    all_month_batches = []

    for sid, uid_quantities in month_allocations.items():
        sinfo = supplier_info.get(sid, {})
        weekly_max = sinfo.get('weekly_max', 1)
        monthly_max = sinfo.get('monthly_max', 999)
        prep_days = sinfo.get('prep_days', 0)
        transit_days = sinfo.get('transit_days', 0)
        lead_time = prep_days + transit_days

        earliest_arrival = algo_start_date + timedelta(days=lead_time)
        supplier_workdays = [wd for wd in available_workdays if wd >= earliest_arrival]
        if not supplier_workdays:
            supplier_workdays = [available_workdays[-1]]

        supplier_weeks = OrderedDict()
        for wd in supplier_workdays:
            wk = wd.isocalendar()[:2]
            if wk not in supplier_weeks:
                supplier_weeks[wk] = []
            supplier_weeks[wk].append(wd)

        supplier_week_keys = list(supplier_weeks.keys())
        num_supplier_weeks = len(supplier_week_keys)

        # 甲方20260824修复：按设备类型码大码分组，逐个设备类型码独立
        # 应用"同设备类型码每周/每月最大到货次数"限制
        big_dict = defaultdict(dict)
        for uid, qty in uid_quantities.items():
            big_code = uid_to_big.get(uid, '')
            if big_code:
                big_dict[big_code][uid] = qty

        for big_code, big_uid_qty in big_dict.items():
            total_big_qty = sum(big_uid_qty.values())
            if total_big_qty <= 0:
                continue

            total_batches = min(weekly_max * num_supplier_weeks, monthly_max, total_big_qty)
            total_batches = max(1, total_batches)

            base_qty = total_big_qty // total_batches
            remainder_qty = total_big_qty % total_batches

            # 该设备类型码在各周分配批次数（每周不超过 weekly_max）
            batches_per_week = [0] * num_supplier_weeks
            remaining_batches = total_batches
            for wi in range(num_supplier_weeks):
                if remaining_batches <= 0:
                    break
                per_week = min(weekly_max, remaining_batches)
                batches_per_week[wi] = per_week
                remaining_batches -= per_week

            batch_idx = 0
            remaining_big_qty = dict(big_uid_qty)
            for wi, num_batches in enumerate(batches_per_week):
                if num_batches <= 0:
                    continue
                week_key = supplier_week_keys[wi]
                week_days = supplier_weeks[week_key]
                for bi in range(num_batches):
                    if week_days:
                        day_idx = min(int(bi * len(week_days) / num_batches), len(week_days) - 1)
                        batch_date = week_days[day_idx]
                    else:
                        batch_date = available_workdays[-1]

                    batch_qty = base_qty + (1 if batch_idx < remainder_qty else 0)
                    batch_idx += 1

                    if batch_qty <= 0:
                        continue

                    current_total_remaining = sum(remaining_big_qty.values())
                    if current_total_remaining <= 0:
                        break
                    batch_qty = min(batch_qty, current_total_remaining)

                    detail_alloc = {}
                    detail_remaining = batch_qty
                    detail_items = list(remaining_big_qty.items())
                    for di, (uid, detail_qty) in enumerate(detail_items):
                        if detail_remaining <= 0 or detail_qty <= 0:
                            continue
                        if di == len(detail_items) - 1:
                            alloc = min(detail_remaining, detail_qty)
                        else:
                            alloc = max(1, int(batch_qty * detail_qty / current_total_remaining))
                            alloc = min(alloc, detail_remaining, detail_qty)
                        if alloc > 0:
                            detail_alloc[uid] = alloc
                            detail_remaining -= alloc
                            remaining_big_qty[uid] = detail_qty - alloc

                    if detail_alloc:
                        all_month_batches.append({
                            'supplier_id': sid,
                            'sinfo': sinfo,
                            'date': batch_date,
                            'batch_qty': batch_qty,
                            'detail_alloc': detail_alloc,
                            'lead_time': lead_time,
                            'prep_days': prep_days,
                            'transit_days': transit_days,
                        })

    # ============================================================
    # 7.2b 后处理：统一约束感知的批次安排
    #   约束：
    #     C1 每日到货批次数 ≤ daily_max_batches
    #     C2 每日到货明细行数 ≤ daily_max_batches（每批恰一行，自动满足）
    #     C3 同(供应商, 设备类型码大码)每周批次数 ≤ weekly_max 【问题2修复】
    #     C4 同(供应商, 设备类型码大码)每月批次数 ≤ monthly_max（生成阶段已保证）
    #   说明：生成阶段每个批次只对应一个大码且仅含一个合同明细，因此
    #     “明细行数”与“批次数”等价；这里只做“顺延安排”与“同供应商
    #     同日合并”，不再做跨周拆分，从根本上避免每周到货次数超限。
    # ============================================================
    for b in all_month_batches:
        uids = list(b['detail_alloc'].keys())
        b['big_code'] = uid_to_big.get(uids[0], '') if uids else ''

    # 每周容量（可用工作日数 × 每日最大批次数）
    week_of_date = {wd: wd.isocalendar()[:2] for wd in available_workdays}
    week_cap = defaultdict(int)
    for wd in available_workdays:
        week_cap[week_of_date[wd]] += daily_max_batches

    # 迭代消解超载周：把超载周中同(供应商,大码)的批次合并到其它周的批次，
    # 合并只减少该大码的批次数（每周仍≤weekly_max、每月仍≤monthly_max），
    # 从而解决首尾被截断的周无法容纳“每周一批”的问题【问题2根源】
    for _ in range(200):
        week_batches = defaultdict(list)
        for b in all_month_batches:
            week_batches[week_of_date[b['date']]].append(b)
        over = [(wk, len(bs)) for wk, bs in week_batches.items()
                if len(bs) > week_cap.get(wk, 0)]
        if not over:
            break
        over.sort(key=lambda t: -t[1])
        wk = over[0][0]
        merged = False
        for b in sorted(week_batches[wk], key=lambda x: x['date']):
            sid = b['supplier_id']
            big = b['big_code']
            targets = [bb for bb in all_month_batches
                       if bb is not b and bb['supplier_id'] == sid and bb['big_code'] == big]
            targets.sort(key=lambda bb: (
                week_cap.get(week_of_date[bb['date']], 0)
                - len(week_batches.get(week_of_date[bb['date']], []))
            ), reverse=True)
            for bb in targets:
                wk2 = week_of_date[bb['date']]
                if wk2 == wk:
                    continue
                if len(week_batches.get(wk2, [])) >= week_cap.get(wk2, 0):
                    continue
                bb['batch_qty'] += b['batch_qty']
                for uid, qty in b['detail_alloc'].items():
                    bb['detail_alloc'][uid] = bb['detail_alloc'].get(uid, 0) + qty
                all_month_batches.remove(b)
                merged = True
                break
            if merged:
                break
        if not merged:
            break

    all_month_batches.sort(key=lambda x: x['date'])

    for b in all_month_batches:
        sid = b['supplier_id']
        big = b['big_code']
        weekly_max = supplier_info.get(sid, {}).get('weekly_max', 1)
        earliest = b['date']
        placed = False
        # 优先在满足每周限制的前提下找最早可用工作日
        for wd in available_workdays:
            if wd < earliest:
                continue
            if daily_used[wd] >= daily_max_batches:
                continue
            wk = wd.isocalendar()[:2]
            if weekly_used[(sid, big, wk)] >= weekly_max:
                continue
            b['date'] = wd
            daily_used[wd] += 1
            weekly_used[(sid, big, wk)] += 1
            placed = True
            break
        # 兜底：若同周已满，则顺延到任一剩余槽位（仍记录本周占用）
        if not placed:
            for wd in available_workdays:
                if wd < earliest:
                    continue
                if daily_used[wd] >= daily_max_batches:
                    continue
                b['date'] = wd
                daily_used[wd] += 1
                weekly_used[(sid, big, wd.isocalendar()[:2])] += 1
                placed = True
                break
        if not placed:
            b['date'] = available_workdays[-1]
            daily_used[available_workdays[-1]] += 1
            weekly_used[(sid, big, available_workdays[-1].isocalendar()[:2])] += 1

    # 合并同一天同一供应商的所有批次为一个批次（保留原语义）
    date_supplier_batches = defaultdict(list)
    for b in all_month_batches:
        key = (b['date'], b['supplier_id'])
        date_supplier_batches[key].append(b)

    merge_count = 0
    for (d, sid), batches in date_supplier_batches.items():
        if len(batches) <= 1:
            continue
        main_batch = batches[0]
        for b in batches[1:]:
            main_batch['batch_qty'] += b['batch_qty']
            for uid, qty in b['detail_alloc'].items():
                main_batch['detail_alloc'][uid] = main_batch['detail_alloc'].get(uid, 0) + qty
            all_month_batches.remove(b)
            merge_count += 1

    if merge_count > 0:
        print(f"  {month_str}: 合并同供应商同日批次 {merge_count} 个")

    month_slot_check = defaultdict(int)
    for b in all_month_batches:
        month_slot_check[b['date']] += 1
    over = {d: c for d, c in month_slot_check.items() if c > daily_max_batches}
    if over:
        print(f"  ⚠ {month_str}: {len(over)}天批次超限")
    else:
        print(f"  ✓ {month_str}: 每日批次≤{daily_max_batches} (共{len(all_month_batches)}批)")

    # 7.3 生成到货计划明细
    batch_id_counter = defaultdict(int)
    for batch in all_month_batches:
        sid = batch['supplier_id']
        sinfo = batch['sinfo']
        detail_alloc = batch['detail_alloc']
        arrival_date = batch['date']
        prep_days = batch['prep_days']
        transit_days = batch['transit_days']
        lead_time = batch['lead_time']

        batch_id_counter[(sid, month_str)] += 1
        batch_no = f"{sid}-{month_str}-{batch_id_counter[(sid, month_str)]}"

        for uid, alloc_qty in detail_alloc.items():
            if alloc_qty <= 0:
                continue

            batch_seq[(sid, uid)] += 1

            contract_info = uid_map[uid]
            mat_code = contract_info.get('物资编码', '')
            mm = material_map.get(mat_code, {})

            daily_arrival_plan.append({
                '通知日期': algo_start_date,
                '到货日期': arrival_date,
                '所属周': f"{arrival_date.isocalendar()[0]}-W{arrival_date.isocalendar()[1]:02d}",
                '所属月': month_str,
                '设备类别': mm.get('dev_type', ''),
                '设备类别名称': mm.get('dev_type_name', ''),
                '设备分类': mm.get('dev_category', ''),
                '设备分类名称': mm.get('dev_category_name', ''),
                '设备类型码（大码）': mm.get('big_code', ''),
                '设备类型码描述（大码）': mm.get('big_code_desc', ''),
                '供应商编号': sid,
                '供应商名称': sinfo.get('name', ''),
                '物资编码': mat_code,
                '合同标识': contract_info.get('合同标识', ''),
                '合同明细标识': contract_info.get('合同明细标识', ''),
                '到货数量': alloc_qty,
                '到货批次号': batch_no,
                '备货周期(天)': prep_days,
                '物流在途(天)': transit_days,
                '前置期(天)': lead_time,
            })

daily_arrival_plan.sort(key=lambda x: (x['到货日期'], x['供应商编号']))

df_daily = pd.DataFrame(daily_arrival_plan)
if not df_daily.empty:
    df_daily['通知日期'] = df_daily['通知日期'].astype(str)
    df_daily['到货日期'] = df_daily['到货日期'].astype(str)

print(f"\n=== 日到货计划: {len(daily_arrival_plan)} 条 ===")

# ============================================================
# 8. 待检仓容量告警 + 每日批次超限告警
# ============================================================
capacity_list = []
for _, row in dfs['capacity'].iterrows():
    if str(row['库区类型']) == '待检仓':
        capacity_list.append({
            'name': str(row['库区名称']),
            'capacity': int(row['库区容量']),
            'current_stock': int(row['当前库存']),
            'daily_max_batches': daily_max_batches,
        })

if not capacity_list:
    capacity_list = [{'name': '待检仓', 'capacity': float('inf'), 'current_stock': 0, 'daily_max_batches': daily_max_batches}]

daily_arrival_qty = defaultdict(int)
daily_batch_nos = defaultdict(set)
daily_line_count = defaultdict(int)
for plan in daily_arrival_plan:
    d = plan['到货日期']
    if isinstance(d, str):
        d = datetime.strptime(d, '%Y-%m-%d').date()
    daily_arrival_qty[d] += plan['到货数量']
    daily_batch_nos[d].add(plan['到货批次号'])
    daily_line_count[d] += 1

daily_batch_count = {d: len(nos) for d, nos in daily_batch_nos.items()}

capacity_alerts = []
for cap_info in capacity_list:
    current_stock = cap_info['current_stock']
    capacity = cap_info['capacity']
    for wd in workdays:
        arrival = daily_arrival_qty.get(wd, 0)
        current_stock += arrival
        if current_stock > capacity:
            capacity_alerts.append({
                '库区名称': cap_info['name'],
                '日期': wd,
                '累计库存': int(current_stock),
                '库区容量': capacity,
                '是否超容': '是',
                '超容数量': int(current_stock - capacity),
                '当日到货量': arrival,
                '当日批次数': daily_batch_count.get(wd, 0),
            })

df_capacity_alerts = pd.DataFrame(capacity_alerts)
if not df_capacity_alerts.empty:
    df_capacity_alerts['日期'] = df_capacity_alerts['日期'].astype(str)

daily_batch_alerts = []
for cap_info in capacity_list:
    daily_max = cap_info['daily_max_batches']
    for wd in workdays:
        batch_count = daily_batch_count.get(wd, 0)
        line_count = daily_line_count.get(wd, 0)
        if batch_count > daily_max or line_count > daily_max:
            daily_batch_alerts.append({
                '库区名称': cap_info['name'],
                '日期': wd,
                '当日批次数': batch_count,
                '当日明细行数': line_count,
                '每日最大接收批次数': daily_max,
                '是否超限': '是',
                '超限批次数': max(0, batch_count - daily_max),
                '超限明细行数': max(0, line_count - daily_max),
                '当日到货量': daily_arrival_qty.get(wd, 0),
            })

df_daily_batch_alerts = pd.DataFrame(daily_batch_alerts)
if not df_daily_batch_alerts.empty:
    df_daily_batch_alerts['日期'] = df_daily_batch_alerts['日期'].astype(str)

print(f"=== 每日批次超限告警: {len(daily_batch_alerts)} 条 ===")

# ============================================================
# 9. 合同不足告警
# ============================================================
df_shortage = pd.DataFrame(contract_shortage)
print(f"\n=== 合同不足告警: {len(contract_shortage)} 条 ===")
for s in contract_shortage:
    print(f"  {s['物资编码']}: {s['说明']}, 净需求={s['净需求']}, 缺口={s['缺口数量']}")

# ============================================================
# 10. 输出Excel
# ============================================================
df_output_daily = df_daily[['通知日期', '到货日期', '所属周', '所属月',
                             '设备类别', '设备类别名称', '设备分类', '设备分类名称',
                             '设备类型码（大码）', '设备类型码描述（大码）',
                             '供应商编号', '供应商名称',
                             '物资编码', '合同标识', '合同明细标识', '到货数量',
                             '到货批次号', '备货周期(天)', '物流在途(天)', '前置期(天)']]

text_cols_daily = ['设备类别', '设备分类', '设备类型码（大码）', '物资编码', '供应商编号', '合同标识', '合同明细标识']
for col in text_cols_daily:
    if col in df_output_daily.columns:
        df_output_daily[col] = df_output_daily[col].astype(str)

df_contract_out = pd.DataFrame(contract_allocation)
if not df_contract_out.empty:
    df_contract_out = df_contract_out[['物资编码', '合同标识', '合同明细标识',
                                        '供应商编号', '供应商名称', '合同数量',
                                        '已到货数量', '执行进度(%)', '合同占比(%)',
                                        '同物资总进度(%)', '本次分配数量',
                                        '分配后进度(%)', '分配后剩余合同量', '供应商评分']]
    text_cols_contract = ['物资编码', '合同标识', '合同明细标识', '供应商编号']
    for col in text_cols_contract:
        if col in df_contract_out.columns:
            df_contract_out[col] = df_contract_out[col].astype(str)

df_net = pd.DataFrame(net_demand_rows)
if not df_net.empty:
    df_net['物资编码'] = df_net['物资编码'].astype(str)
    df_net = df_net[['物资编码', '月份', '总需求', '供货数量', '已入待检仓数量',
                     '供货净抵扣', '非合格在库库存', '合格在库库存',
                     '未配送库存', '安全库存', '净需求']]

if not df_shortage.empty:
    df_shortage['物资编码'] = df_shortage['物资编码'].astype(str)

df_notified_dates = pd.DataFrame(notified_date_details)
if not df_notified_dates.empty:
    df_notified_dates['要求到货日期'] = df_notified_dates['要求到货日期'].astype(str)
    df_notified_dates['物资编码'] = df_notified_dates['物资编码'].astype(str)
    df_notified_dates['供应商编号'] = df_notified_dates['供应商编号'].astype(str)

output_dir = os.path.dirname(os.path.abspath(__file__))
output_file = os.path.join(output_dir, '到货计划排程结果8.24.xlsx')

sheets = {
    '日到货计划明细': df_output_daily,
    '待检仓容量告警清单': df_capacity_alerts,
    '每日批次超限告警清单': df_daily_batch_alerts,
    '合同分配情况': df_contract_out,
    '合同不足告警清单': df_shortage,
    '净需求汇总': df_net,
    '已供货通知排除日期': df_notified_dates,
}

try:
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        for sheet_name, sheet_df in sheets.items():
            sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)
except PermissionError:
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = os.path.join(output_dir, f'到货计划排程结果_{ts}.xlsx')
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        for sheet_name, sheet_df in sheets.items():
            sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)

print(f"\n{'='*60}")
print(f"到货计划排程完成！结果保存至: {output_file}")
print(f"  日到货计划明细: {len(df_output_daily)} 条")
print(f"  合同分配情况: {len(df_contract_out)} 条")
print(f"  合同不足告警: {len(df_shortage)} 条")
print(f"  净需求汇总: {len(df_net)} 条")
print(f"{'='*60}")

# ============================================================
# 11. 优化点验证输出
# ============================================================
print(f"\n=== 甲方20260824优化点验证 ===")

# ---- 问题1 + 问题3: 净需求公式正确性 ----
print(f"\n[问题1/3] 净需求公式验证（含安全库存、供货-已入待检）")
for r in net_demand_rows:
    if r['月份'].startswith('202603'):
        recompute = r['总需求'] - r['供货净抵扣'] - r['非合格在库库存'] - (r['合格在库库存'] - r['未配送库存'] - r['安全库存'])
        marker = '✓' if r['净需求'] == max(0, recompute) else '✗'
        print(f"  {r['物资编码']} [{r['月份']}]: 需求={r['总需求']}, "
              f"供货净抵扣={r['供货净抵扣']}, 非合格={r['非合格在库库存']}, "
              f"合格在库-未配送-安全库存={r['合格在库库存']-r['未配送库存']-r['安全库存']}, "
              f"净需求={r['净需求']} {marker}")

# 3月设备类型码覆盖检查：应到11个
march_codes_demand = set()
for _, row in dfs['demand'].iterrows():
    if str(row['所属月份']).startswith('202603'):
        march_codes_demand.add(str(row['设备类型码大码']))
march_codes_result = set(str(p['设备类型码（大码）']) for p in daily_arrival_plan if str(p['所属月']).startswith('202603'))
print(f"  3月需求设备类型码: {len(march_codes_demand)} 个")
print(f"  3月排程结果设备类型码: {len(march_codes_result)} 个")
missing = march_codes_demand - march_codes_result
if missing:
    print(f"  ✗ 漏规划的设备类型码: {sorted(missing)}")
else:
    print(f"  ✓ 所有3月需求的设备类型码均已被规划")

# ---- 问题2: 同设备类型码每周最大到货次数 ----
print(f"\n[问题2] 同设备类型码每周最大到货次数验证")
week_batch = defaultdict(set)  # (供应商编号, 大码, 周) -> 批次号集合
for p in daily_arrival_plan:
    sid = p['供应商编号']
    big = str(p['设备类型码（大码）'])
    d = p['到货日期']
    if isinstance(d, str):
        d = datetime.strptime(d, '%Y-%m-%d').date()
    wk = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
    week_batch[(sid, big, wk)].add(p['到货批次号'])

violations = []
for (sid, big, wk), nos in sorted(week_batch.items()):
    weekly_max = supplier_info.get(sid, {}).get('weekly_max', 1)
    cnt = len(nos)
    name = supplier_info.get(sid, {}).get('name', sid)
    if cnt > weekly_max:
        violations.append((name, big, wk, cnt, weekly_max))

if violations:
    print(f"  ✗ 违反同设备类型码每周最大到货次数的记录: {len(violations)} 条")
    for v in violations[:20]:
        print(f"    {v[0]} / 大码{v[1]} / {v[2]}: {v[3]}批 > 允许{v[4]}批")
else:
    print(f"  ✓ 全部满足同设备类型码每周最大到货次数约束")

# ---- 需求5: 已供货通知日期排除 ----
print(f"\n[需求5] 已供货通知日期排除")
notified_set = set(notified_dates)
def _to_date(d):
    if isinstance(d, str):
        return datetime.strptime(d, '%Y-%m-%d').date()
    if isinstance(d, datetime):
        return d.date()
    return d
plans_on_notified = [p for p in daily_arrival_plan if _to_date(p['到货日期']) in notified_set]
print(f"  排除日期: {sorted(notified_set)}")
print(f"  排除日期上的到货计划: {len(plans_on_notified)}条 {'✓' if len(plans_on_notified) == 0 else '✗'}")

# ---- 供应商到货统计 ----
print(f"\n供应商到货统计:")
for sid, sinfo in supplier_info.items():
    plans = [p for p in daily_arrival_plan if p['供应商编号'] == sid]
    if plans:
        total_qty = sum(p['到货数量'] for p in plans)
        print(f"  {sinfo['name']}: {len(plans)}条记录, 总量={total_qty}")