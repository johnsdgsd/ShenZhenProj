import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict, deque
import math


file_path = r"C:\Users\H5966\Desktop\检定排程\检定仓情况-20260723.xlsx"  

df_overall = pd.read_excel(file_path, sheet_name='整体情况')
df_line_info = pd.read_excel(file_path, sheet_name='检定线信息表')
df_chamber_type = pd.read_excel(file_path, sheet_name='检定仓类型表')
df_chamber_config = pd.read_excel(file_path, sheet_name='检定仓配置表')
df_arrival = pd.read_excel(file_path, sheet_name='到货排程-到货计划旧表')
df_demand = pd.read_excel(file_path, sheet_name='需求明细')
df_spec = pd.read_excel(file_path, sheet_name='规格设备码信息表')
df_qualified = pd.read_excel(file_path, sheet_name='合格品库存信息表')
df_unqualified = pd.read_excel(file_path, sheet_name='非合格品库存')
df_time_config = pd.read_excel(file_path, sheet_name='排程时间配置')
df_gap_config = pd.read_excel(file_path, sheet_name='调度时间间隔配置')


def clean_columns(df):
    df.columns = df.columns.str.strip().str.replace(' ', '')
    return df


df_overall = clean_columns(df_overall)
df_line_info = clean_columns(df_line_info)
df_chamber_type = clean_columns(df_chamber_type)
df_chamber_config = clean_columns(df_chamber_config)
df_arrival = clean_columns(df_arrival)
df_demand = clean_columns(df_demand)
df_spec = clean_columns(df_spec)
df_qualified = clean_columns(df_qualified)
df_unqualified = clean_columns(df_unqualified)
df_time_config = clean_columns(df_time_config)
df_gap_config = clean_columns(df_gap_config)


dev_code_to_cat = {}
dev_code_to_access = {}
for _, row in df_spec.iterrows():
    code = row['设备码']
    cat = row['设备分类']
    access = row['接入方式'] if pd.notna(row['接入方式']) else ''
    dev_code_to_cat[code] = cat
    dev_code_to_access[code] = access


df_overall[['线体编号', '线体名称', '检定仓类型']] = df_overall[['线体编号', '线体名称', '检定仓类型']].ffill()
df_overall['所检设备表类型'] = df_overall['所检设备表类型'].astype(str).str.replace('\n', ' ', regex=False)


def parse_device_category(desc):
    desc = desc.lower()
    if '单相电能表' in desc:
        return '单相电能表'
    elif '三相直接表' in desc or '三相互感表' in desc or '三相互感电能表' in desc:
        return '三相电能表'
    elif '集中器' in desc or '负荷控制终端' in desc or '配变监测终端' in desc or '智能量测终端' in desc or '厂站终端' in desc:
        return '智能量测终端'
    elif '10kv电压互感器' in desc:
        return '10kV电压互感器'
    elif '20kv电压互感器' in desc:
        return '20kV电压互感器'
    elif '10kv电流互感器' in desc:
        return '10kV电流互感器'
    elif '20kv电流互感器' in desc:
        return '20kV电流互感器'
    elif '普通型低压电流互感器' in desc or '大变比型低压电流互感器' in desc or 'dbi型低压电流互感器' in desc:
        return '低压电流互感器'
    else:
        return None


chambers = {}
chamber_type_id_map = {}  
for _, row in df_overall.iterrows():
    line_id = row['线体编号']
    chamber_id = row['检定仓编号']
    if pd.isna(chamber_id):
        continue
    device_desc = row['所检设备表类型']
    capacity = row['表位数']
    if pd.isna(capacity):
        continue
    dev_cat = parse_device_category(device_desc)
    if dev_cat is None:
        continue
    chamber_key = (line_id, chamber_id)
    if chamber_key not in chambers:
        chambers[chamber_key] = {'capacity': {}, 'type_name': '', 'line_id': line_id, 'dev_count': 0}
    if dev_cat in chambers[chamber_key]['capacity']:
        chambers[chamber_key]['capacity'][dev_cat] = max(chambers[chamber_key]['capacity'][dev_cat], int(capacity))
    else:
        chambers[chamber_key]['capacity'][dev_cat] = int(capacity)
        chambers[chamber_key]['dev_count'] += 1


for _, row in df_chamber_config.iterrows():
    line_id = int(row['检定线ID'])
    chamber_id = str(row['检定仓编号'])
    chamber_key = (line_id, chamber_id)
    if chamber_key in chambers:
        chamber_type_id = int(row['仓类型ID'])
        chamber_type_id_map[chamber_key] = chamber_type_id
        type_name_row = df_chamber_type[df_chamber_type['仓类型ID'] == chamber_type_id]
        if not type_name_row.empty:
            chambers[chamber_key]['type_name'] = type_name_row.iloc[0]['仓类型名称']

print(f"从整体情况表加载了 {len(chambers)} 个检定仓")


spec_time = {}
for _, row in df_spec.iterrows():
    cat = row['设备分类']
    if pd.notna(row['自动检定时间']):
        spec_time[cat] = int(row['自动检定时间'])
default_times = {
    '三相电能表': 414,
    '单相电能表': 108,
    '智能量测终端': 414,
    '10kV电压互感器': 25,
    '20kV电压互感器': 25,
    '10kV电流互感器': 25,
    '20kV电流互感器': 25,
    '低压电流互感器': 25,
}
for k, v in default_times.items():
    if k not in spec_time:
        spec_time[k] = v


line_name_map = {}
for _, row in df_line_info.iterrows():
    if pd.notna(row['检定线ID']):
        line_name_map[int(row['检定线ID'])] = str(row['检定线名称']).strip()


time_map = {}
if not df_time_config.empty:
    for _, row in df_time_config.iterrows():
        work_date = row['工作日日期']
        start_time = row['开始时间']
        end_time = row['结束时间']
        if hasattr(start_time, 'hour'):
            sh, sm = start_time.hour, start_time.minute
        else:
            sh, sm = map(int, str(start_time).split(':'))
        if hasattr(end_time, 'hour'):
            eh, em = end_time.hour, end_time.minute
        else:
            eh, em = map(int, str(end_time).split(':'))
        time_map[work_date] = (sh, sm, eh, em)


gap_map = {}
if not df_gap_config.empty:
    for _, row in df_gap_config.iterrows():
        line_id = int(row['线体编号'])
        gap_sec = int(row['调度时间间隔（秒）'])
        gap_map[line_id] = gap_sec / 60.0
else:
    for line_id in line_name_map.keys():
        gap_map[line_id] = 5.0


if not df_time_config.empty:
    first_date = df_time_config.iloc[0]['工作日日期']
    if hasattr(first_date, 'date'):
        base_date = datetime(first_date.year, first_date.month, first_date.day, 9, 0, 0)
    else:
        base_date = datetime(2026, 3, 1, 9, 0, 0)
else:
    base_date = datetime(2026, 3, 1, 9, 0, 0)


inventory = defaultdict(int)
for _, row in df_qualified.iterrows():
    dev_code = row['设备码']
    qualified = row['合格品库存'] if pd.notna(row['合格品库存']) else 0
    undelivered = row['未配送库存'] if pd.notna(row['未配送库存']) else 0
    safety = row['安全库存'] if pd.notna(row['安全库存']) else 0
    available = qualified - undelivered - safety
    if available > 0:
        inventory[dev_code] += int(available)
print("初始库存（按设备码）:", dict(inventory))


pending_batches = deque()


for _, row in df_unqualified.iterrows():
    batch_no = row['到货批次号']
    dev_code = row['设备类型码']
    qty = int(row['可检库存'])
    est_date = datetime(2026, 1, 1, 0, 0, 0)
    pending_batches.append([str(batch_no), dev_code, qty, qty, est_date])


for _, row in df_arrival.iterrows():
    batch_no = row['到货批次号']
    if pd.isna(batch_no):
        continue
    dev_code = row['设备规格']  
    qty = int(row['数量'])
    est_date = row['预计到货日期']
    if pd.isna(est_date):
        est_date = datetime(2026, 3, 31)
    pending_batches.append([str(batch_no), dev_code, qty, qty, est_date])


pending_batches = deque(sorted(pending_batches, key=lambda x: (x[4], x[0])))
print(f"待处理批次总数: {len(pending_batches)}")


demand_by_month = defaultdict(list)  # month -> [(dev_code, qty)]
for _, row in df_demand.iterrows():
    month = str(row['所属月份'])
    dev_code = row['设备类型码大码']  
    qty = int(row['申请数量'])
    demand_by_month[month].append((dev_code, qty))
months = sorted(demand_by_month.keys())


def get_priority(dev_code):
    cat = dev_code_to_cat.get(dev_code, '')
    if cat == '智能量测终端':
        return 0
    elif cat == '三相电能表':
        return 1
    elif cat == '单相电能表':
        return 2
    else:
        return 3


MAX_DAY_SEARCH = 365 * 10  # 最大搜索天数，防止死循环

def is_workday(day):
    """判断是否为工作日：time_map 中有明确配置，或默认为周一至周五。"""
    if day in time_map:
        return True
    return day.weekday() < 5  # 周一至周五默认为工作日

def get_workday_times(day):
    """获取指定日期的工作时间配置。time_map 中有配置则使用配置，否则默认 9:00-17:00。"""
    if day in time_map:
        return time_map[day]
    return (9, 0, 17, 0)

def find_next_workday(day):
    """从 day 开始（不含），找到下一个工作日。"""
    next_day = day + timedelta(days=1)
    for _ in range(MAX_DAY_SEARCH):
        if is_workday(next_day):
            return next_day
        next_day += timedelta(days=1)
    raise OverflowError(f"在 {MAX_DAY_SEARCH} 天内未找到下一个工作日，请检查排程时间配置。")


def get_next_start_minutes(prev_end_minutes, duration, line_id, earliest_start_minutes=0):
    gap = gap_map.get(line_id, 5.0)

    if prev_end_minutes == 0:
        candidate_min = 0
    else:
        prev_end_abs = base_date + timedelta(minutes=prev_end_minutes)
        planned_start_abs = prev_end_abs + timedelta(minutes=gap)
        candidate_min = int((planned_start_abs - base_date).total_seconds() / 60)

    for _ in range(MAX_DAY_SEARCH):
        start_abs = base_date + timedelta(minutes=candidate_min)
        day = start_abs.date()

        if not is_workday(day):
            next_day = find_next_workday(day)
            sh, sm, eh, em = get_workday_times(next_day)
            candidate_min = int((datetime(next_day.year, next_day.month, next_day.day, sh, sm, 0) - base_date).total_seconds() / 60)
            continue

        sh, sm, eh, em = get_workday_times(day)
        work_start_today = datetime(day.year, day.month, day.day, sh, sm, 0)
        work_end_today = datetime(day.year, day.month, day.day, eh, em, 0)

        if start_abs < work_start_today:
            start_abs = work_start_today
        elif start_abs > work_end_today:
            # 开始时间晚于下班时间，顺延到下一工作日
            next_day = find_next_workday(day)
            sh2, sm2, eh2, em2 = get_workday_times(next_day)
            candidate_min = int((datetime(next_day.year, next_day.month, next_day.day, sh2, sm2, 0) - base_date).total_seconds() / 60)
            continue

        end_abs = start_abs + timedelta(minutes=duration)
        if end_abs > work_end_today:
            # 结束时间超过下班时间，顺延到下一工作日
            next_day = find_next_workday(day)
            sh2, sm2, eh2, em2 = get_workday_times(next_day)
            candidate_min = int((datetime(next_day.year, next_day.month, next_day.day, sh2, sm2, 0) - base_date).total_seconds() / 60)
            continue

        # 检查最早开始（预计到货日期）
        earliest_abs = base_date + timedelta(minutes=earliest_start_minutes)
        if start_abs < earliest_abs:
            earliest_date = earliest_abs.date()
            if is_workday(earliest_date):
                sh_e, sm_e, eh_e, em_e = get_workday_times(earliest_date)
                start_earliest = datetime(earliest_date.year, earliest_date.month, earliest_date.day, sh_e, sm_e, 0)
                candidate_min = int((start_earliest - base_date).total_seconds() / 60)
                continue
            else:
                next_day = find_next_workday(earliest_date)
                sh_e, sm_e, eh_e, em_e = get_workday_times(next_day)
                start_earliest = datetime(next_day.year, next_day.month, next_day.day, sh_e, sm_e, 0)
                candidate_min = int((start_earliest - base_date).total_seconds() / 60)
                continue

        return int((start_abs - base_date).total_seconds() / 60)

    raise OverflowError(f"时间计算超过 {MAX_DAY_SEARCH} 天仍未找到合适时段，请检查排程配置。")


chamber_time = {ch: 0 for ch in chambers.keys()}
schedule_details = []

def schedule_batch(batch_no, dev_code, quantity, is_priority, month, earliest_start=0):
    if quantity <= 0:
        return 0
    dev_cat = dev_code_to_cat.get(dev_code)
    if dev_cat is None:
        raise ValueError(f"设备码 {dev_code} 无法映射到设备分类")
    # 找出支持该设备分类的仓，并过滤掉不符合接入方式的仓（优化点6）
    available = []
    for ch, info in chambers.items():
        cap = info['capacity'].get(dev_cat)
        if cap and cap > 0:
            # 检查终端接入方式限制：仓类型ID=5（终端/三相兼容仓）只允许经互感接入的终端
            if dev_cat == '智能量测终端' and chamber_type_id_map.get(ch, 0) == 5:
                access = dev_code_to_access.get(dev_code, '')
                if '经互感' not in access:
                    continue  # 排除该仓
            available.append((ch, cap))
    if not available:
        raise ValueError(f"没有支持设备类型 {dev_cat} 的检定仓！")

    # 仓排序：优先选择专用仓（支持设备种类少），再按最早空闲时间（优化点2）
    available.sort(key=lambda x: (chambers[x[0]]['dev_count'], chamber_time[x[0]]))

    remaining = quantity
    sub_counter = 1
    while remaining > 0:
        ch, max_cap = available[0]
        batch_qty = min(remaining, max_cap)
        duration = spec_time[dev_cat]
        line_id = ch[0]
        start_min = get_next_start_minutes(chamber_time[ch], duration, line_id, earliest_start)
        end_min = start_min + duration
        start_time = base_date + timedelta(minutes=start_min)
        end_time = base_date + timedelta(minutes=end_min)
        priority_label = 'P' if is_priority else 'N'
        internal_batch = f"{month}-{batch_no}-{priority_label}-{sub_counter}"
        schedule_details.append({
            '月份': month,
            '检定线ID': ch[0],
            '检定线名称': line_name_map.get(ch[0], ''),
            '检定仓编号': ch[1],
            '检定仓类型': chambers[ch]['type_name'],
            '设备类型': dev_cat,
            '设备码': dev_code,
            '到货批次号': batch_no,
            '是否为需求优先': '是' if is_priority else '否',
            '内部批次号': internal_batch,
            '每批数量': batch_qty,
            '预计开始时间': start_time,
            '预计完成时间': end_time,
            '检定时长(天)': round(duration / 1440, 1),
            '检定时长(分钟/批)': duration
        })
        chamber_time[ch] = end_min
        inventory[dev_code] += batch_qty
        remaining -= batch_qty
        available[0] = (ch, max_cap)
        available.sort(key=lambda x: (chambers[x[0]]['dev_count'], chamber_time[x[0]]))
        sub_counter += 1
    return quantity


for month in months:
    # 当月需求汇总（按设备码）
    demand_dict = defaultdict(int)
    for dev_code, qty in demand_by_month[month]:
        demand_dict[dev_code] += qty

    # 按优先级排序
    sorted_dev_codes = sorted(demand_dict.keys(), key=lambda x: get_priority(x))

    for dev_code in sorted_dev_codes:
        need = demand_dict[dev_code]
        avail = inventory.get(dev_code, 0)
        if avail >= need:
            inventory[dev_code] -= need
            continue

        deficit = need - avail
        inventory[dev_code] = 0

        
        while deficit > 0 and pending_batches:
            # 寻找匹配设备码的批次
            found_idx = None
            for i, (b, d, r, _, dt) in enumerate(pending_batches):
                if d == dev_code:
                    found_idx = i
                    break
            if found_idx is None:
                raise ValueError(f"月份 {month} 设备码 {dev_code} 短缺 {deficit}，但无对应到货批次")
            pending_batches.rotate(-found_idx)
            batch_no, batch_dev, remain, orig_qty, est_date = pending_batches[0]

            # 计算最大仓容量
            dev_cat = dev_code_to_cat.get(dev_code)
            max_cap_for_dev = max(info['capacity'][dev_cat] for info in chambers.values() if dev_cat in info['capacity'])

            if remain >= deficit:
                # 批次充足：需求向上取整，多出部分作为备货
                total_take = math.ceil(deficit / max_cap_for_dev) * max_cap_for_dev
                total_take = min(total_take, remain)
                demand_take = deficit
                stock_take = total_take - demand_take
            else:
                # 批次不足，全部取走作为需求
                total_take = remain
                demand_take = remain
                stock_take = 0

            # 安排需求部分（需求优先）
            if demand_take > 0:
                est_minutes = int((est_date - base_date).total_seconds() / 60) if pd.notna(est_date) else 0
                schedule_batch(batch_no, dev_code, demand_take, is_priority=True, month=month, earliest_start=est_minutes)

            # 安排备货部分（非需求优先），同样要遵守到货日期
            if stock_take > 0:
                est_minutes = int((est_date - base_date).total_seconds() / 60) if pd.notna(est_date) else 0
                schedule_batch(batch_no, dev_code, stock_take, is_priority=False, month=month, earliest_start=est_minutes)

            # 更新批次剩余
            if total_take == remain:
                pending_batches.popleft()
            else:
                pending_batches[0][2] -= total_take
            deficit -= demand_take  # 只减去需求部分

    # 当月需求满足后，提前检定剩余批次（非需求优先）
    temp_list = list(pending_batches)
    for batch in temp_list:
        batch_no, dev_code, remain, _, est_date = batch
        if remain <= 0:
            pending_batches.popleft()
            continue
        dev_cat = dev_code_to_cat.get(dev_code)
        if dev_cat is None:
            print(f"警告: 批次 {batch_no} 设备码 {dev_code} 无对应设备分类，跳过")
            pending_batches.popleft()
            continue
        # 检查是否支持
        support = False
        for info in chambers.values():
            if dev_cat in info['capacity']:
                support = True
                break
        if not support:
            print(f"警告: 批次 {batch_no} 类型 {dev_cat} 无对应检定仓，跳过")
            pending_batches.popleft()
            continue
        est_minutes = int((est_date - base_date).total_seconds() / 60) if pd.notna(est_date) else 0
        schedule_batch(batch_no, dev_code, remain, is_priority=False, month=month, earliest_start=est_minutes)
        pending_batches.popleft()


df_details = pd.DataFrame(schedule_details)

# 检定排程明细（汇总）
df_schedule_summary = df_details.groupby(
    ['月份', '检定线ID', '检定线名称', '设备类型', '设备码', '到货批次号', '是否为需求优先']
).agg(
    总检定数量=('每批数量', 'sum'),
    批次数=('内部批次号', 'nunique')
).reset_index()

# 检定时间明细（排序）
df_details_sorted = df_details.sort_values(['预计开始时间', '检定线ID'])

# 仓利用率统计
df_util = df_details.groupby(
    ['月份', '检定线ID', '检定线名称', '检定仓编号', '检定仓类型']
).agg(
    总批次数=('内部批次号', 'nunique'),
    总检定量=('每批数量', 'sum')
).reset_index()

# 到货批次分配明细
df_batch_alloc = df_details.groupby(
    ['月份', '到货批次号', '设备类型', '设备码', '是否为需求优先']
).agg(
    分配数量=('每批数量', 'sum')
).reset_index()
df_batch_alloc['检定时长(分钟/批)'] = df_batch_alloc['设备类型'].map(spec_time)

# 原始到货批次
arrival_set = set()
for _, row in df_arrival.iterrows():
    if pd.notna(row['到货批次号']):
        arrival_set.add((str(row['到货批次号']), row['设备分类'], row['设备规格'], int(row['数量'])))
for _, row in df_unqualified.iterrows():
    if pd.notna(row['到货批次号']):
        arrival_set.add((str(row['到货批次号']), row['设备分类'], row['设备类型码'], int(row['可检库存'])))
original_arrivals = []
for batch_no, dev_cat, dev_code, qty in arrival_set:
    original_arrivals.append({
        '到货批次号': batch_no,
        '设备类型': dev_cat,
        '设备码': dev_code,
        '原始到货量': qty,
        '检定时长(分钟/批)': spec_time.get(dev_cat, 414)
    })
df_original = pd.DataFrame(original_arrivals).drop_duplicates(subset=['到货批次号'])

# 月度需求汇总（按设备码）
demand_summary = []
for month, demands in demand_by_month.items():
    for dev_code, qty in demands:
        dev_cat = dev_code_to_cat.get(dev_code, '未知')
        demand_summary.append({'月份': month, '设备类型': dev_cat, '设备码': dev_code, '需求数量': qty})
df_demand_summary = pd.DataFrame(demand_summary)

# 检定仓配置
chamber_config_rows = []
for (line_id, chamber_id), info in chambers.items():
    line_name = line_name_map.get(line_id, '')
    max_cap = max(info['capacity'].values()) if info['capacity'] else 0
    chamber_config_rows.append({
        '检定线ID': line_id,
        '检定线名称': line_name,
        '检定仓编号': chamber_id,
        '仓类型': info['type_name'],
        '每仓最大容量': max_cap
    })
df_chamber_config_output = pd.DataFrame(chamber_config_rows)

# 写入Excel
output_file = '检定排程计划_优化版_无加班.xlsx'
with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
    df_schedule_summary.to_excel(writer, sheet_name='检定排程明细', index=False)
    df_details_sorted.to_excel(writer, sheet_name='检定时间明细', index=False)
    df_util.to_excel(writer, sheet_name='仓利用率统计', index=False)
    df_batch_alloc.to_excel(writer, sheet_name='到货批次分配明细', index=False)
    df_original.to_excel(writer, sheet_name='原始到货批次', index=False)
    df_demand_summary.to_excel(writer, sheet_name='月度需求汇总', index=False)
    df_chamber_config_output.to_excel(writer, sheet_name='检定仓配置', index=False)

print(f"排程完成！结果保存至: {output_file}")
print(f"共生成 {len(df_details)} 个检定子任务，总计检定设备 {df_details['每批数量'].sum()} 台。")