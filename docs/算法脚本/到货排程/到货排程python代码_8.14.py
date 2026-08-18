import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict, OrderedDict
import math
import os

# ============================================================
# 1. 读取输入数据
# ============================================================
file_path = r"C:\Users\H5966\Desktop\检定排程\到货计划排程入参8.14.xlsx"

dfs = {}

dfs['demand'] = pd.read_excel(file_path, sheet_name='月度需用',
    converters={'物资编码': str, '设备类型码': str, '设备类型码大码': str})
dfs['qualified'] = pd.read_excel(file_path, sheet_name='合格品库存详情（立库+成品仓）',
    converters={'设备类型码': str, '设备类型码大码': str})
dfs['unqualified'] = pd.read_excel(file_path, sheet_name='非合格品库存详情（待检仓+立库）',
    converters={'设备类型码': str})
dfs['contracts'] = pd.read_excel(file_path, sheet_name='订单合同清单',
    converters={'物资编码': str})
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

# ============================================================
# 3. 解析供应商信息（列名已更新为8.14版本）
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
        'monthly_max': int(row['同设备类型码每月最大到货次数']) if pd.notna(row['同设备类型码每月最大到货次数']) else 4,
    }

# ============================================================
# 4. 需求1: 净需求计算
#    公式：合格品库存抵扣 = 合格品库存 - 未配送库存 - 安全库存
# ============================================================
# 4.1 物资编码 → 设备类型码大码、设备分类、设备类别等映射
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

# 4.2 月度需用汇总（按物资编码）
demand_by_mat = defaultdict(lambda: {'total': 0, 'details': []})
for _, row in dfs['demand'].iterrows():
    mat_code = str(row['物资编码'])
    qty = int(row['计划数量'])
    demand_by_mat[mat_code]['total'] += qty
    demand_by_mat[mat_code]['details'].append({
        'month': str(row['所属月份']),
        'dev_type_code': str(row['设备类型码']),
        'dev_type_desc': str(row['设备类型码描述']),
        'qty': qty,
    })

# 4.3 合格品库存可用量（按设备类型码大码）
#     公式：合格品库存抵扣 = 合格品库存 - 未配送库存 - 安全库存
qualified_avail = defaultdict(int)
for _, row in dfs['qualified'].iterrows():
    stock = int(row['合格在库库存']) if pd.notna(row['合格在库库存']) else 0
    undelivered = int(row['未配送库存']) if pd.notna(row['未配送库存']) else 0
    safety = int(row['安全库存']) if pd.notna(row['安全库存']) else 0
    available = max(0, stock - undelivered - safety)
    big_code = str(row['设备类型码大码'])
    if big_code and big_code != 'nan':
        qualified_avail[big_code] += available

# 4.4 非合格品库存（按设备类型码大码，通过设备类型码→大码映射转换）
unqualified_avail = defaultdict(int)
for _, row in dfs['unqualified'].iterrows():
    dev_code = str(row['设备类型码'])
    qty = int(row['非合格在库库存']) if pd.notna(row['非合格在库库存']) else 0
    big_code = dev_code_to_big.get(dev_code, dev_code)
    unqualified_avail[big_code] += qty

# 4.5 已供货通知（按物资编码，供货数量 - 已入待检仓数量）
notified_avail = defaultdict(int)
for _, row in dfs['notified'].iterrows():
    mat_code = str(row['物资编码'])
    supply = int(row['供货数量']) if pd.notna(row['供货数量']) else 0
    received = int(row['已入待检仓数量']) if pd.notna(row['已入待检仓数量']) else 0
    notified_avail[mat_code] += max(0, supply - received)

# 4.6 计算净需求
net_demand = {}
for mat_code, info in demand_by_mat.items():
    total = info['total']
    big_code = material_map.get(mat_code, {}).get('big_code', '')
    q_avail = qualified_avail.get(big_code, 0)
    u_avail = unqualified_avail.get(big_code, 0)
    n_avail = notified_avail.get(mat_code, 0)

    remaining = total
    q_used = min(q_avail, remaining)
    remaining -= q_used
    u_used = min(u_avail, remaining)
    remaining -= u_used
    n_used = min(n_avail, remaining)
    remaining -= n_used

    if remaining > 0:
        net_demand[mat_code] = {
            'total': total, 'q_used': q_used, 'u_used': u_used,
            'n_used': n_used, 'net': remaining, 'big_code': big_code,
            'details': info['details'],
        }

print(f"\n=== 净需求汇总 ({len(net_demand)} 个物资编码) ===")
for mc, nd in net_demand.items():
    print(f"  {mc}: 总需求={nd['total']}, 合格品抵扣={nd['q_used']}, "
          f"非合格品抵扣={nd['u_used']}, 已通知抵扣={nd['n_used']}, 净需求={nd['net']}")

# ============================================================
# 5. 需求2+7: 合同分配（新逻辑）
#    需求7：先按进度低优先补足到总进度，再按合同占比分配
#    需求6：增加合同占比展示
# ============================================================
# 5.1 按物资编码分组合同
contracts_by_mat = defaultdict(list)
for _, row in dfs['contracts'].iterrows():
    mat_code = str(row['物资编码'])
    contracts_by_mat[mat_code].append({
        'detail_id': str(row['合同明细标识']),
        'contract_id': str(row['合同标识']),
        'mat_code': mat_code,
        'mat_name': str(row.get('物资编码名称', '')),
        'dev_type': str(row.get('设备类别', '')),
        'dev_type_name': str(row.get('设备类别名称', '')),
        'dev_category': str(row.get('设备分类', '')),
        'dev_category_name': str(row.get('设备分类名称', '')),
        'contract_qty': int(row['合同数量']),
        'arrived_qty': int(row['已到货数量']),
        'supplier_id': str(row['供应商编号']),
        'supplier_name': str(row['供应商名称']),
    })

# 5.2 合同分配（新逻辑：先补足进度 → 再按占比）
contract_allocation = []
contract_shortage = []

for mat_code, nd_info in net_demand.items():
    net_qty = nd_info['net']
    contracts = contracts_by_mat.get(mat_code, [])

    if not contracts:
        contract_shortage.append({
            '物资编码': mat_code, '净需求': net_qty, '合同总量': 0,
            '缺口数量': net_qty, '说明': '无对应合同'
        })
        continue

    for c in contracts:
        c['remaining'] = max(0, c['contract_qty'] - c['arrived_qty'])
        c['progress'] = c['arrived_qty'] / c['contract_qty'] if c['contract_qty'] > 0 else 1.0

    total_remaining = sum(c['remaining'] for c in contracts)
    total_contract = sum(c['contract_qty'] for c in contracts)
    total_arrived = sum(c['arrived_qty'] for c in contracts)

    # 计算同物资编码的总合同执行进度
    overall_progress = total_arrived / total_contract if total_contract > 0 else 0

    if total_remaining < net_qty:
        contract_shortage.append({
            '物资编码': mat_code, '净需求': net_qty,
            '合同总量': total_contract, '合同剩余': total_remaining,
            '缺口数量': net_qty - total_remaining, '说明': '合同剩余量不足'
        })

    # 合同占比
    for c in contracts:
        c['proportion'] = c['contract_qty'] / total_contract if total_contract > 0 else 0

    allocatable = min(net_qty, total_remaining)
    remaining_alloc = allocatable

    # ================================================================
    # 阶段一：按进度低优先，补足到同物资编码总进度
    # 排序：进度低者优先，进度相同→评分高者优先
    # ================================================================
    contracts.sort(key=lambda c: (
        c['progress'],
        -supplier_info.get(c['supplier_id'], {}).get('rating', 0)
    ))

    phase1_allocations = {}  # detail_id -> 阶段一分配量

    for c in contracts:
        if remaining_alloc <= 0:
            break
        # 该合同要达到总进度需要的量
        target_arrived = int(c['contract_qty'] * overall_progress)
        shortage_to_target = max(0, target_arrived - c['arrived_qty'])
        shortage_to_target = min(shortage_to_target, c['remaining'])
        alloc = min(shortage_to_target, remaining_alloc)
        if alloc > 0:
            phase1_allocations[c['detail_id']] = alloc
            remaining_alloc -= alloc

    # ================================================================
    # 阶段二：剩余量按合同占比分配
    # ================================================================
    if remaining_alloc > 0:
        for idx, c in enumerate(contracts):
            if remaining_alloc <= 0:
                break
            already_alloc = phase1_allocations.get(c['detail_id'], 0)
            still_available = c['remaining'] - already_alloc
            if still_available <= 0:
                continue
            if idx == len(contracts) - 1:
                alloc = min(remaining_alloc, still_available)
            else:
                alloc = min(int(allocatable * c['proportion']), still_available, remaining_alloc)
            if alloc > 0:
                phase1_allocations[c['detail_id']] = already_alloc + alloc
                remaining_alloc -= alloc

    # 阶段二剩余取整差额按进度优先补足
    if remaining_alloc > 0:
        for c in contracts:
            if remaining_alloc <= 0:
                break
            already_alloc = phase1_allocations.get(c['detail_id'], 0)
            still_available = c['remaining'] - already_alloc
            extra = min(remaining_alloc, still_available)
            if extra > 0:
                phase1_allocations[c['detail_id']] = already_alloc + extra
                remaining_alloc -= extra

    # 汇总输出
    for c in contracts:
        alloc_qty = phase1_allocations.get(c['detail_id'], 0)
        if alloc_qty > 0:
            new_progress = (c['arrived_qty'] + alloc_qty) / c['contract_qty'] * 100 if c['contract_qty'] > 0 else 0
            contract_allocation.append({
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

# ============================================================
# 6. 需求3+5: 均匀规划到货日期
#    需求3：去掉每月最大到货次数约束
#    需求5：到货日期 = 算法起始日 + 前置期（工作日偏移）
# ============================================================
algo_start_date = workdays[0]
print(f"\n算法起始日期: {algo_start_date}")

# 6.1 按供应商、合同明细汇总分配量
supplier_plan_input = defaultdict(lambda: defaultdict(int))
for a in contract_allocation:
    sid = a['供应商编号']
    detail_id = a['合同明细标识']
    supplier_plan_input[sid][detail_id] += a['本次分配数量']

# 6.2 为每个供应商的每个合同明细规划到货日期
daily_arrival_plan = []
batch_seq = defaultdict(int)

for sid, detail_quantities in supplier_plan_input.items():
    sinfo = supplier_info.get(sid, {})
    weekly_max = sinfo.get('weekly_max', 1)
    prep_days = sinfo.get('prep_days', 0)
    transit_days = sinfo.get('transit_days', 0)
    lead_time = prep_days + transit_days

    total_supplier_qty = sum(detail_quantities.values())
    if total_supplier_qty <= 0:
        continue

    # 前置期偏移：最早可用到货日期 = 算法起始日 + lead_time 个工作日
    first_available_idx = min(max(0, lead_time - 1), len(workdays) - 1)
    first_available_date = workdays[first_available_idx]

    # 过滤该供应商可用工作日
    supplier_workdays = [wd for wd in workdays if wd >= first_available_date]
    if not supplier_workdays:
        supplier_workdays = [workdays[-1]]

    # 重建该供应商的周分组
    supplier_weeks = OrderedDict()
    for wd in supplier_workdays:
        wk = wd.isocalendar()[:2]
        if wk not in supplier_weeks:
            supplier_weeks[wk] = []
        supplier_weeks[wk].append(wd)

    supplier_week_keys = list(supplier_weeks.keys())
    num_supplier_weeks = len(supplier_week_keys)

    # 需求3：去掉每月最大到货次数约束，只保留每周最大约束
    max_by_week = weekly_max * num_supplier_weeks
    total_batches = min(max_by_week, total_supplier_qty)
    total_batches = max(1, total_batches)

    # 均匀分配到各周
    batches_per_week = [0] * num_supplier_weeks
    remaining_batches = total_batches
    for wi in range(num_supplier_weeks):
        if remaining_batches <= 0:
            break
        per_week = min(weekly_max, remaining_batches)
        batches_per_week[wi] = per_week
        remaining_batches -= per_week

    while remaining_batches > 0:
        for wi in range(num_supplier_weeks):
            if remaining_batches <= 0:
                break
            if batches_per_week[wi] < weekly_max:
                batches_per_week[wi] += 1
                remaining_batches -= 1

    # 为每批分配日期（在周内均匀分布）
    batch_dates = []
    for wi, num_batches in enumerate(batches_per_week):
        if num_batches <= 0:
            continue
        week_key = supplier_week_keys[wi]
        week_days = supplier_weeks[week_key]
        for bi in range(num_batches):
            if week_days:
                day_idx = min(int(bi * len(week_days) / num_batches), len(week_days) - 1)
                batch_dates.append(week_days[day_idx])

    while len(batch_dates) < total_batches:
        batch_dates.append(batch_dates[-1] if batch_dates else workdays[-1])
    batch_dates = batch_dates[:total_batches]

    # 每批数量均匀分配
    base_qty = total_supplier_qty // total_batches
    remainder_qty = total_supplier_qty % total_batches

    for bi, arrival_date in enumerate(batch_dates):
        if bi < remainder_qty:
            batch_qty = base_qty + 1
        else:
            batch_qty = base_qty
        if batch_qty <= 0:
            continue

        total_detail_qty = sum(detail_quantities.values())
        detail_alloc_remaining = batch_qty
        detail_items = list(detail_quantities.items())

        for di, (detail_id, detail_qty) in enumerate(detail_items):
            if detail_alloc_remaining <= 0:
                break
            if di == len(detail_items) - 1:
                alloc = detail_alloc_remaining
            else:
                alloc = max(0, int(batch_qty * detail_qty / total_detail_qty))
                alloc = min(alloc, detail_alloc_remaining)

            if alloc > 0:
                batch_seq[(sid, detail_id)] += 1
                batch_no = f"{sid}-{detail_id}-{batch_seq[(sid, detail_id)]}"

                contract_info = next(
                    (a for a in contract_allocation
                     if a['供应商编号'] == sid and a['合同明细标识'] == detail_id),
                    {}
                )
                mat_code = contract_info.get('物资编码', '')
                mm = material_map.get(mat_code, {})

                daily_arrival_plan.append({
                    '通知日期': algo_start_date,
                    '到货日期': arrival_date,
                    '所属周': f"{arrival_date.isocalendar()[0]}-W{arrival_date.isocalendar()[1]:02d}",
                    '所属月': f"{arrival_date.year}-{arrival_date.month:02d}",
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
                    '合同明细标识': detail_id,
                    '到货数量': alloc,
                    '到货批次号': batch_no,
                    '备货周期(天)': prep_days,
                    '物流在途(天)': transit_days,
                    '前置期(天)': lead_time,
                })
                detail_alloc_remaining -= alloc

# 按日期排序
daily_arrival_plan.sort(key=lambda x: (x['到货日期'], x['供应商编号']))

df_daily = pd.DataFrame(daily_arrival_plan)
if not df_daily.empty:
    df_daily['通知日期'] = df_daily['通知日期'].astype(str)
    df_daily['到货日期'] = df_daily['到货日期'].astype(str)

print(f"\n=== 日到货计划: {len(daily_arrival_plan)} 条 ===")

# ============================================================
# 7. 需求4: 待检仓容量告警（不限制每日接收批次数）
# ============================================================
capacity_list = []
for _, row in dfs['capacity'].iterrows():
    if str(row['库区类型']) == '待检仓':
        capacity_list.append({
            'name': str(row['库区名称']),
            'capacity': int(row['库区容量']),
            'current_stock': int(row['当前库存']),
        })

if not capacity_list:
    print("警告: 未找到待检仓容量配置")
    capacity_list = [{'name': '待检仓', 'capacity': float('inf'), 'current_stock': 0}]

daily_arrival_qty = defaultdict(int)
daily_batch_count = defaultdict(int)
for plan in daily_arrival_plan:
    d = plan['到货日期']
    if isinstance(d, str):
        d = datetime.strptime(d, '%Y-%m-%d').date()
    daily_arrival_qty[d] += plan['到货数量']
    daily_batch_count[d] += 1

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

print(f"\n=== 待检仓容量告警: {len(capacity_alerts)} 条 ===")

# ============================================================
# 8. 需求5: 合同不足告警
# ============================================================
df_shortage = pd.DataFrame(contract_shortage)
print(f"\n=== 合同不足告警: {len(contract_shortage)} 条 ===")
for s in contract_shortage:
    print(f"  {s['物资编码']}: {s['说明']}, 净需求={s['净需求']}, 缺口={s['缺口数量']}")

# ============================================================
# 9. 需求6: 输出Excel
# ============================================================
# 日到货计划明细（需求2：增加设备类别、设备分类、设备类型码大码、设备类型码大码描述）
df_output_daily = df_daily[['通知日期', '到货日期', '所属周', '所属月',
                             '设备类别', '设备类别名称', '设备分类', '设备分类名称',
                             '设备类型码（大码）', '设备类型码描述（大码）',
                             '供应商编号', '供应商名称',
                             '物资编码', '合同标识', '合同明细标识', '到货数量',
                             '到货批次号', '备货周期(天)', '物流在途(天)', '前置期(天)']]

# 合同分配情况（需求6：增加合同占比展示）
df_contract_out = pd.DataFrame(contract_allocation)
if not df_contract_out.empty:
    df_contract_out = df_contract_out[['物资编码', '合同标识', '合同明细标识',
                                        '供应商编号', '供应商名称', '合同数量',
                                        '已到货数量', '执行进度(%)', '合同占比(%)',
                                        '同物资总进度(%)', '本次分配数量',
                                        '分配后进度(%)', '分配后剩余合同量', '供应商评分']]

# 净需求汇总
net_rows = []
for mc, nd in net_demand.items():
    net_rows.append({
        '物资编码': mc, '总需求': nd['total'], '合格品库存抵扣': nd['q_used'],
        '非合格品库存抵扣': nd['u_used'], '已供货通知抵扣': nd['n_used'],
        '净需求': nd['net'],
    })
df_net = pd.DataFrame(net_rows)

# 输出Excel
output_dir = os.path.dirname(os.path.abspath(__file__))
output_file = os.path.join(output_dir, '到货计划排程结果.xlsx')

sheets = {
    '日到货计划明细': df_output_daily,
    '待检仓容量告警清单': df_capacity_alerts,
    '合同分配情况': df_contract_out,
    '合同不足告警清单': df_shortage,
    '净需求汇总': df_net,
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
print(f"  待检仓容量告警: {len(df_capacity_alerts)} 条")
print(f"  合同分配情况: {len(df_contract_out)} 条")
print(f"  合同不足告警: {len(df_shortage)} 条")
print(f"  净需求汇总: {len(df_net)} 个物资编码")
print(f"{'='*60}")