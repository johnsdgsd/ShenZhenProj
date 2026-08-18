import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict, deque
import math

# 1. 读取原始数据 
file_path = r"C:\Users\H5966\Desktop\检定排程\检定仓情况-20260807.xlsx"  

df_overall = pd.read_excel(file_path, sheet_name='整体情况')
df_line_info = pd.read_excel(file_path, sheet_name='检定线信息表')
df_chamber_type = pd.read_excel(file_path, sheet_name='检定仓类型表')
df_chamber_config = pd.read_excel(file_path, sheet_name='检定仓配置表')
df_arrival = pd.read_excel(file_path, sheet_name='到货排程-到货计划旧表', converters={'设备规格': str})
df_demand = pd.read_excel(file_path, sheet_name='需求明细', converters={'设备类型码大码': str, '设备码': str})
df_spec = pd.read_excel(file_path, sheet_name='规格设备码信息表', converters={'设备码': str})
df_qualified = pd.read_excel(file_path, sheet_name='合格品库存信息表', converters={'设备码': str})
df_unqualified = pd.read_excel(file_path, sheet_name='非合格品库存', converters={'设备类型码': str})
df_time_config = pd.read_excel(file_path, sheet_name='排程时间配置')
df_gap_config = pd.read_excel(file_path, sheet_name='调度时间间隔配置')
df_non_demand_target = pd.read_excel(file_path, sheet_name='非需求设备目标设备类型配置', converters={'设备类型码大码': str, '目标设备类型码': str})


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
df_non_demand_target = clean_columns(df_non_demand_target)

# 2.1. 构建设备码大小码映射（从需求明细表：设备码(小码) → 设备类型码大码）
dev_code_to_big_code = {}
for _, row in df_demand.iterrows():
    small_code = row['设备码'] if pd.notna(row['设备码']) else ''
    big_code = row['设备类型码大码'] if pd.notna(row['设备类型码大码']) else ''
    if small_code and big_code and small_code != big_code:
        dev_code_to_big_code[small_code] = big_code
if dev_code_to_big_code:
    print(f"大小码映射: {dev_code_to_big_code}")

# 2.3. 构建非需求设备目标设备类型映射（设备类型码大码 → [(目标设备类型码, 分配比例%)]）
non_demand_target_config = defaultdict(list)
for _, row in df_non_demand_target.iterrows():
    original_code = str(row['设备类型码大码'])
    target_code = str(row['目标设备类型码'])
    percentage = float(row['分配比例（%）'])
    non_demand_target_config[original_code].append((target_code, percentage))
if non_demand_target_config:
    print(f"非需求设备目标类型映射: {dict(non_demand_target_config)}")

# 2.2. 构建低压电流互感器子类型映射（基于设备码描述区分大变比、DBI、普通型）
dev_code_to_low_voltage_subtype = {}
for _, row in df_spec.iterrows():
    code = str(row['设备码'])
    cat = str(row['设备分类']) if pd.notna(row['设备分类']) else ''
    if cat == '低压电流互感器':
        desc = str(row['设备码描述']) if pd.notna(row['设备码描述']) else ''
        if '大变比' in desc:
            dev_code_to_low_voltage_subtype[code] = '低压电流互感器_大变比'
        elif 'dbi' in desc.lower() or 'DBI' in desc:
            dev_code_to_low_voltage_subtype[code] = '低压电流互感器_DBI'
        else:
            dev_code_to_low_voltage_subtype[code] = '低压电流互感器'
if dev_code_to_low_voltage_subtype:
    print(f"低压电流互感器子类型映射: {dev_code_to_low_voltage_subtype}")

# 2. 构建基础映射 
dev_code_to_cat = {}
dev_code_to_access = {}
for _, row in df_spec.iterrows():
    code = row['设备码']
    cat = row['设备分类']
    access = row['接入方式'] if pd.notna(row['接入方式']) else ''
    # 低压电流互感器使用子类型分类
    if cat == '低压电流互感器':
        cat = dev_code_to_low_voltage_subtype.get(str(code), cat)
    dev_code_to_cat[code] = cat
    dev_code_to_access[code] = access

df_overall[['线体编号', '线体名称', '检定仓类型', '检定仓编号']] = df_overall[['线体编号', '线体名称', '检定仓类型', '检定仓编号']].ffill()
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
    elif '大变比型低压电流互感器' in desc:
        return '低压电流互感器_大变比'
    elif 'dbi型低压电流互感器' in desc:
        return '低压电流互感器_DBI'
    elif '普通型低压电流互感器' in desc:
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

#  3. 设备检定时间 
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
    '20kV电压互感器': 30,
    '10kV电流互感器': 25,
    '20kV电流互感器': 30,
    '低压电流互感器': 25,
    '低压电流互感器_大变比': 25,
    '低压电流互感器_DBI': 25,
}
for k, v in default_times.items():
    if k not in spec_time:
        spec_time[k] = v

line_name_map = {}
for _, row in df_line_info.iterrows():
    if pd.notna(row['检定线ID']):
        line_name_map[int(row['检定线ID'])] = str(row['检定线名称']).strip()

# 4. 配置参数 
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
        if isinstance(work_date, str):
            work_date = datetime.strptime(work_date, '%Y-%m-%d').date()
        elif hasattr(work_date, 'date'):
            work_date = work_date.date()
        time_map[work_date] = (sh, sm, eh, em)

gap_map = {}
overtime_map = {}
if not df_gap_config.empty:
    for _, row in df_gap_config.iterrows():
        line_id = int(row['线体编号'])
        gap_sec = int(row['调度时间间隔（秒）'])
        gap_map[line_id] = gap_sec / 60.0
        overtime_hours = float(row['允许加班时长（小时）']) if pd.notna(row['允许加班时长（小时）']) else 0
        overtime_map[line_id] = overtime_hours
else:
    for line_id in line_name_map.keys():
        gap_map[line_id] = 5.0
        overtime_map[line_id] = 0

print(f"各线体加班时长配置: {overtime_map}")

if not df_time_config.empty:
    first_date = df_time_config.iloc[0]['工作日日期']
    if hasattr(first_date, 'date'):
        base_date = datetime(first_date.year, first_date.month, first_date.day, 9, 0, 0)
    else:
        base_date = datetime(2026, 3, 1, 9, 0, 0)
else:
    base_date = datetime(2026, 3, 1, 9, 0, 0)

# 5. 初始化合格品库存 
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

# 6. 构造待处理批次队列 
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

#  7. 解析需求明细 
# 先补充映射：从需求明细表的"设备分类"列读取，补充规格设备码信息表中缺失的设备码映射
for _, row in df_demand.iterrows():
    dev_code = row['设备类型码大码']
    dev_cat_from_demand = row['设备分类'] if pd.notna(row['设备分类']) else ''
    if dev_cat_from_demand and dev_code not in dev_code_to_cat:
        # 低压电流互感器也使用子类型映射
        if dev_cat_from_demand == '低压电流互感器':
            dev_cat_from_demand = dev_code_to_low_voltage_subtype.get(str(dev_code), dev_cat_from_demand)
        dev_code_to_cat[dev_code] = dev_cat_from_demand

demand_by_month = defaultdict(list)  # month -> [(dev_code, qty)]
for _, row in df_demand.iterrows():
    month = str(row['所属月份'])
    dev_code = row['设备类型码大码']  
    qty = int(row['申请数量'])
    demand_by_month[month].append((dev_code, qty))
months = sorted(demand_by_month.keys())

# 8. 设备类型优先级 
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

#  9. 时间计算辅助函数 
MAX_DAY_SEARCH = 365 * 10
# 最晚完工日期：排程时间配置中最后一天
MAX_WORK_DATE = datetime(2026, 4, 30).date()

def is_workday(day):
    """仅认排程时间配置中明确定义的工作日，不自动补全周末以外的工作日"""
    if day > MAX_WORK_DATE:
        return False
    return day in time_map

def get_workday_times(day):
    if day in time_map:
        return time_map[day]
    return (9, 0, 17, 0)

def find_next_workday(day):
    next_day = day + timedelta(days=1)
    for _ in range(MAX_DAY_SEARCH):
        if is_workday(next_day):
            return next_day
        next_day += timedelta(days=1)
    raise OverflowError(f"在 {MAX_DAY_SEARCH} 天内未找到下一个工作日，请检查排程时间配置。")

# 10. 时间计算函数（支持加班：允许在正常下班时间后继续排程，但不超过加班时长上限）
def get_next_start_minutes(prev_end_minutes, duration, line_id, earliest_start_minutes=0):
    gap = gap_map.get(line_id, 5.0)
    overtime_hours = overtime_map.get(line_id, 0)

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
        overtime_end_today = work_end_today + timedelta(hours=overtime_hours)

        if start_abs < work_start_today:
            start_abs = work_start_today
        elif start_abs >= overtime_end_today:
            next_day = find_next_workday(day)
            sh2, sm2, eh2, em2 = get_workday_times(next_day)
            candidate_min = int((datetime(next_day.year, next_day.month, next_day.day, sh2, sm2, 0) - base_date).total_seconds() / 60)
            continue

        end_abs = start_abs + timedelta(minutes=duration)
        if end_abs > overtime_end_today:
            next_day = find_next_workday(day)
            sh2, sm2, eh2, em2 = get_workday_times(next_day)
            candidate_min = int((datetime(next_day.year, next_day.month, next_day.day, sh2, sm2, 0) - base_date).total_seconds() / 60)
            continue

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

#  11. 核心排程函数 
chamber_time = {ch: 0 for ch in chambers.keys()}
schedule_details = []

def schedule_batch(batch_no, dev_code, quantity, is_priority, month, earliest_start=0, target_dev_code=None):
    if quantity <= 0:
        return 0
    dev_cat = dev_code_to_cat.get(dev_code)
    if dev_cat is None:
        raise ValueError(f"设备码 {dev_code} 无法映射到设备分类")
    # 若未指定目标设备类型码，则默认使用设备码本身
    if target_dev_code is None:
        target_dev_code = dev_code
    available = []
    for ch, info in chambers.items():
        cap = info['capacity'].get(dev_cat)
        if cap and cap > 0:
            if dev_cat == '智能量测终端' and chamber_type_id_map.get(ch, 0) == 5:
                access = dev_code_to_access.get(dev_code, '')
                if '经互感' not in access:
                    continue
            available.append((ch, cap))
    if not available:
        raise ValueError(f"没有支持设备类型 {dev_cat} 的检定仓！")

    # 排序策略（核心改动）：
    # - 单相电能表 + 需求优先：仅使用兼容仓（dev_count > 1），把专用仓容量留给非需求优先批次，
    #   迫使兼容仓承担全部单相表需求优先产能，从而延长兼容仓使用时间到4月2日之后
    # - 其他设备 + 需求优先：专用仓优先（dev_count小）
    # - 非需求优先：仅使用兼容仓（dev_count > 1），若无兼容仓可用则回退到全部仓
    if is_priority and dev_cat == '单相电能表':
        # 单相表需求优先：仅选兼容仓，迫使兼容仓消化全部单相表需求
        compat_only = [x for x in available if chambers[x[0]]['dev_count'] > 1]
        if compat_only:
            available = compat_only
        available.sort(key=lambda x: (chamber_time[x[0]], -chambers[x[0]]['dev_count'], -x[0][0]))
    elif is_priority:
        # 其他设备需求优先：专用仓优先
        available.sort(key=lambda x: (chamber_time[x[0]], chambers[x[0]]['dev_count'], -x[0][0]))
    else:
        # 非需求优先：仅选兼容仓（dev_count > 1），强制使用兼容仓吸收富余产能
        compat_only = [x for x in available if chambers[x[0]]['dev_count'] > 1]
        if compat_only:
            available = compat_only
        available.sort(key=lambda x: (chamber_time[x[0]], -chambers[x[0]]['dev_count'], -x[0][0]))

    remaining = quantity
    sub_counter = 1
    while remaining > 0:
        if is_priority and dev_cat == '单相电能表':
            compat_only = [x for x in available if chambers[x[0]]['dev_count'] > 1]
            if compat_only:
                available = compat_only
            available.sort(key=lambda x: (chamber_time[x[0]], -chambers[x[0]]['dev_count'], -x[0][0]))
        elif is_priority:
            available.sort(key=lambda x: (chamber_time[x[0]], chambers[x[0]]['dev_count'], -x[0][0]))
        else:
            compat_only = [x for x in available if chambers[x[0]]['dev_count'] > 1]
            if compat_only:
                available = compat_only
            available.sort(key=lambda x: (chamber_time[x[0]], -chambers[x[0]]['dev_count'], -x[0][0]))
        ch, max_cap = available[0]
        batch_qty = min(remaining, max_cap)
        duration = spec_time[dev_cat]
        line_id = ch[0]
        try:
            start_min = get_next_start_minutes(chamber_time[ch], duration, line_id, earliest_start)
        except OverflowError:
            print(f"警告: 设备码 {dev_code} 批次 {batch_no} 剩余 {remaining} 无法在 {MAX_WORK_DATE} 前排程，跳过")
            remaining = 0
            break
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
            '目标设备类型码': target_dev_code,
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
        sub_counter += 1
    return quantity

# 辅助函数：获取某设备类型的最大仓容量
def get_max_chamber_cap(dev_code):
    dev_cat = dev_code_to_cat.get(dev_code)
    if dev_cat is None:
        return 0
    max_cap = 0
    for ch, info in chambers.items():
        cap = info['capacity'].get(dev_cat, 0)
        if cap > max_cap:
            max_cap = cap
    return max_cap

# 辅助函数：获取某批次在schedule_details中所有P子任务的最晚完成时间（分钟）
def get_batch_last_p_end_minutes(batch_no):
    """返回该批次所有需求优先(P)子任务的最晚完成时间（绝对分钟）"""
    max_end = 0
    for item in schedule_details:
        if item['到货批次号'] == batch_no and item['是否为需求优先'] == '是':
            end_min = int((item['预计完成时间'] - base_date).total_seconds() / 60)
            if end_min > max_end:
                max_end = end_min
    return max_end

# 辅助函数：按目标设备类型配置拆分非需求批次排程
def schedule_non_demand_batch(batch_no, dev_code, quantity, month, earliest_start):
    """根据非需求设备目标设备类型配置，将非需求批次按比例拆分并排程"""
    targets = non_demand_target_config.get(dev_code, [(dev_code, 100)])
    # 若配置中只有一个目标且为100%，直接使用原设备码
    if len(targets) == 1 and targets[0][1] == 100 and targets[0][0] == dev_code:
        return schedule_batch(batch_no, dev_code, quantity, is_priority=False, month=month, earliest_start=earliest_start)
    total_pct = sum(pct for _, pct in targets)
    scheduled = 0
    # 按比例分配（最后一个目标补齐取整差额）
    for idx, (target_code, pct) in enumerate(targets):
        if idx == len(targets) - 1:
            target_qty = quantity - scheduled
        else:
            target_qty = int(quantity * pct / total_pct)
        if target_qty > 0:
            scheduled += schedule_batch(batch_no, target_code, target_qty, is_priority=False,
                                        month=month, earliest_start=earliest_start, target_dev_code=target_code)
    return scheduled

# 12. 按月排程 
for month in months:
    demand_dict = defaultdict(int)
    for dev_code, qty in demand_by_month[month]:
        demand_dict[dev_code] += qty

    # 同优先级内，20kV设备优先排程（确保在共用仓中先于10kV设备排程）
    sorted_dev_codes = sorted(demand_dict.keys(), key=lambda x: (get_priority(x), '20kV' not in dev_code_to_cat.get(x, '')))

    for dev_code in sorted_dev_codes:
        need = demand_dict[dev_code]
        avail = inventory.get(dev_code, 0)
        if avail >= need:
            inventory[dev_code] -= need
            continue

        deficit = need - avail
        inventory[dev_code] = 0

        pending_batches = deque(sorted(pending_batches, key=lambda x: (x[4], x[0])))
        while deficit > 0 and pending_batches:
            found_idx = None
            for i, (b, d, r, _, dt) in enumerate(pending_batches):
                # 大小码匹配：如果批次的设备码是小码，尝试匹配大码需求
                batch_dev = d
                mapped_dev = dev_code_to_big_code.get(batch_dev, batch_dev)
                if batch_dev == dev_code or mapped_dev == dev_code:
                    found_idx = i
                    break
            if found_idx is None:
                print(f"警告: 月份 {month} 设备码 {dev_code} 短缺 {deficit}，但无对应到货批次，跳过")
                deficit = 0
                break
            pending_batches.rotate(-found_idx)
            batch_no, batch_dev, remain, orig_qty, est_date = pending_batches[0]

            dev_cat = dev_code_to_cat.get(dev_code)

            if remain >= deficit:
                # 需求尾仓向上取整：减少空仓，将最后一仓的需求量向上取整到仓容量
                max_cap = get_max_chamber_cap(dev_code)
                if max_cap > 0:
                    rounded_deficit = math.ceil(deficit / max_cap) * max_cap
                    if rounded_deficit <= remain:
                        demand_take = rounded_deficit
                    else:
                        demand_take = deficit
                else:
                    demand_take = deficit
                total_take = demand_take
                stock_take = 0
            else:
                total_take = remain
                demand_take = remain
                stock_take = 0

            if demand_take > 0:
                est_minutes = int((est_date - base_date).total_seconds() / 60) if pd.notna(est_date) else 0
                schedule_batch(batch_no, dev_code, demand_take, is_priority=True, month=month, earliest_start=est_minutes, target_dev_code=dev_code)

            if stock_take > 0:
                est_minutes = int((est_date - base_date).total_seconds() / 60) if pd.notna(est_date) else 0
                schedule_non_demand_batch(batch_no, dev_code, stock_take, month, earliest_start=est_minutes)

            if total_take == remain:
                pending_batches.popleft()
            else:
                pending_batches[0][2] -= total_take
            deficit -= demand_take

        # 修正库存：已满足的需求应从库存中扣除
        # 库存 = 生产量 - 已满足的需求量(deficit_original = need - avail)
        original_deficit = need - avail
        inventory[dev_code] = max(0, inventory[dev_code] - original_deficit)

    # 12.5. 处理剩余批次：仅将未来月份无需求的批次排入当前月份
    # 计算该设备码在所有未来月份中的总需求
    future_demand = defaultdict(int)
    current_month_idx = months.index(month)
    for future_month in months[current_month_idx + 1:]:
        for dev_code, qty in demand_by_month[future_month]:
            future_demand[dev_code] += qty

    new_pending = []
    while pending_batches:
        batch = pending_batches.popleft()
        batch_no, dev_code, remain, orig_qty, est_date = batch
        if remain <= 0:
            continue
        dev_cat = dev_code_to_cat.get(dev_code)
        if dev_cat is None:
            print(f"警告: 批次 {batch_no} 设备码 {dev_code} 无对应设备分类，跳过")
            continue
        support = False
        for info in chambers.values():
            if dev_cat in info['capacity']:
                support = True
                break
        if not support:
            print(f"警告: 批次 {batch_no} 类型 {dev_cat} 无对应检定仓，跳过")
            continue

        future_need = future_demand.get(dev_code, 0)
        if future_need >= remain:
            # 全部留待未来月份的需求排程
            new_pending.append(batch)
        elif future_need > 0:
            # 部分需留待未来：将超出部分排入当前月份（非需求优先），剩余留待后续
            excess = remain - future_need
            est_minutes = int((est_date - base_date).total_seconds() / 60) if pd.notna(est_date) else 0
            # 修复：确保非需求优先(N)的earliest_start不早于同批次需求优先(P)的最晚完成时间
            batch_p_end = get_batch_last_p_end_minutes(batch_no)
            if batch_p_end > est_minutes:
                est_minutes = batch_p_end
            schedule_non_demand_batch(batch_no, dev_code, excess, month, earliest_start=est_minutes)
            batch[2] = future_need
            new_pending.append(batch)
        else:
            # 未来无需求，全部排入当前月份（非需求优先）
            est_minutes = int((est_date - base_date).total_seconds() / 60) if pd.notna(est_date) else 0
            # 修复：确保非需求优先(N)的earliest_start不早于同批次需求优先(P)的最晚完成时间
            batch_p_end = get_batch_last_p_end_minutes(batch_no)
            if batch_p_end > est_minutes:
                est_minutes = batch_p_end
            schedule_non_demand_batch(batch_no, dev_code, remain, month, earliest_start=est_minutes)

    pending_batches = deque(sorted(new_pending, key=lambda x: (x[4], x[0])))

# 12.6. 所有月份处理完毕后，处理剩余批次（非需求优先）
if pending_batches:
    pending_batches = deque(sorted(pending_batches, key=lambda x: (x[4], x[0])))
    last_month = months[-1] if months else '999999'
    while pending_batches:
        batch_no, dev_code, remain, orig_qty, est_date = pending_batches[0]
        if remain <= 0:
            pending_batches.popleft()
            continue
        dev_cat = dev_code_to_cat.get(dev_code)
        if dev_cat is None:
            print(f"警告: 批次 {batch_no} 设备码 {dev_code} 无对应设备分类，跳过")
            pending_batches.popleft()
            continue
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
        # 修复：确保非需求优先(N)的earliest_start不早于同批次需求优先(P)的最晚完成时间
        batch_p_end = get_batch_last_p_end_minutes(batch_no)
        if batch_p_end > est_minutes:
            est_minutes = batch_p_end
        schedule_non_demand_batch(batch_no, dev_code, remain, last_month, earliest_start=est_minutes)
        pending_batches.popleft()

# 13. 输出结果 
df_details = pd.DataFrame(schedule_details)

df_schedule_summary = df_details.groupby(
    ['月份', '检定线ID', '检定线名称', '设备类型', '设备码', '到货批次号', '是否为需求优先']
).agg(
    总检定数量=('每批数量', 'sum'),
    批次数=('内部批次号', 'nunique')
).reset_index()

df_details_sorted = df_details.sort_values(['预计开始时间', '检定线ID'])

df_util = df_details.groupby(
    ['月份', '检定线ID', '检定线名称', '检定仓编号', '检定仓类型']
).agg(
    总批次数=('内部批次号', 'nunique'),
    总检定量=('每批数量', 'sum')
).reset_index()

df_batch_alloc = df_details.groupby(
    ['月份', '到货批次号', '设备类型', '设备码', '是否为需求优先']
).agg(
    分配数量=('每批数量', 'sum')
).reset_index()
df_batch_alloc['检定时长(分钟/批)'] = df_batch_alloc['设备类型'].map(spec_time)

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

demand_summary = []
for month, demands in demand_by_month.items():
    for dev_code, qty in demands:
        dev_cat = dev_code_to_cat.get(dev_code, '未知')
        demand_summary.append({'月份': month, '设备类型': dev_cat, '设备码': dev_code, '需求数量': qty})
df_demand_summary = pd.DataFrame(demand_summary)

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

#  新增：将包含设备码的列转换为字符串，避免科学计数法 
def convert_dev_code_to_str(df):
    if '设备码' in df.columns:
        df['设备码'] = df['设备码'].astype(str)
    if '目标设备类型码' in df.columns:
        df['目标设备类型码'] = df['目标设备类型码'].astype(str)
    return df

df_schedule_summary = convert_dev_code_to_str(df_schedule_summary)
df_details_sorted = convert_dev_code_to_str(df_details_sorted)
df_batch_alloc = convert_dev_code_to_str(df_batch_alloc)
df_original = convert_dev_code_to_str(df_original)
df_demand_summary = convert_dev_code_to_str(df_demand_summary)

# 写入Excel（自动处理文件被占用的情况）
output_file = '检定排程计划_优化版_支持加班.xlsx'
try:
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        df_schedule_summary.to_excel(writer, sheet_name='检定排程明细', index=False)
        df_details_sorted.to_excel(writer, sheet_name='检定时间明细', index=False)
        df_util.to_excel(writer, sheet_name='仓利用率统计', index=False)
        df_batch_alloc.to_excel(writer, sheet_name='到货批次分配明细', index=False)
        df_original.to_excel(writer, sheet_name='原始到货批次', index=False)
        df_demand_summary.to_excel(writer, sheet_name='月度需求汇总', index=False)
        df_chamber_config_output.to_excel(writer, sheet_name='检定仓配置', index=False)
except PermissionError:
    # 文件被占用（如已在Excel中打开），自动生成带时间戳的新文件名
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = f'检定排程计划_优化版_支持加班_{timestamp}.xlsx'
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

# 14. 关键验证输出
print("\n" + "=" * 80)
print("=== 关键验证：20kV电流/电压互感器 ===")
for cat in ['20kV电压互感器', '20kV电流互感器']:
    subset = df_details[df_details['设备类型'] == cat]
    if len(subset) > 0:
        print(f"{cat}: 共{len(subset)}条记录, 总计{subset['每批数量'].sum()}台, "
              f"每批最大{subset['每批数量'].max()}, 每批最小{subset['每批数量'].min()}")
        for _, row in subset.iterrows():
            print(f"  仓:{row['检定仓编号']}, 批:{row['每批数量']}, 时间:{row['预计开始时间']}~{row['预计完成时间']}")
    else:
        print(f"{cat}: 无排程记录！")

print("\n=== 关键验证：低压电流互感器子类型 ===")
for cat in ['低压电流互感器', '低压电流互感器_大变比', '低压电流互感器_DBI']:
    subset = df_details[df_details['设备类型'] == cat]
    if len(subset) > 0:
        print(f"{cat}: 共{len(subset)}条记录, 总计{subset['每批数量'].sum()}台, "
              f"仓列表: {subset['检定仓编号'].unique()}")
    else:
        print(f"{cat}: 无排程记录")

print("\n=== 关键验证：大小码匹配 ===")
if dev_code_to_big_code:
    for small, big in dev_code_to_big_code.items():
        small_records = df_details[df_details['设备码'] == small]
        big_records = df_details[df_details['设备码'] == big]
        print(f"小码 {small} → 大码 {big}")
        print(f"  小码排程: {len(small_records)}条, 总计{small_records['每批数量'].sum()}台")
        print(f"  大码排程: {len(big_records)}条, 总计{big_records['每批数量'].sum()}台")

print("\n=== 关键验证：目标设备类型码 ===")
target_counts = df_details['目标设备类型码'].value_counts()
print(target_counts)

# 15. 需求优先/非需求优先顺序验证
print("\n" + "=" * 80)
print("=== 批次内N/P顺序验证 ===")
# 检查所有批次中是否有N在P之前的情况（区分同月/跨月）
n_before_p_found = False
cross_month_n_before_p = []
for batch_no in df_details['到货批次号'].unique():
    batch_data = df_details[df_details['到货批次号'] == batch_no].sort_values('预计开始时间')
    labels = batch_data['是否为需求优先'].tolist()
    months = batch_data['月份'].tolist()
    for i in range(len(labels) - 1):
        if labels[i] == '否' and labels[i+1] == '是':
            if months[i] == months[i+1]:
                print(f"!!! 同月异常 - 批次 {batch_no}: 第{i}条是N({batch_data.iloc[i]['预计开始时间']}, 月份{months[i]}), 第{i+1}条是P({batch_data.iloc[i+1]['预计开始时间']}, 月份{months[i+1]})")
                n_before_p_found = True
            else:
                cross_month_n_before_p.append((batch_no, months[i], months[i+1]))
if cross_month_n_before_p:
    print("注意：以下为跨月份N→P顺序（N在前月已排程，P在后月新增需求，属正常跨月行为）：")
    for bn, nm, pm in cross_month_n_before_p:
        print(f"  批次 {bn}: N在月份{nm}, P在月份{pm}")
if not n_before_p_found:
    print("所有批次中同月内N不存在于P之前，验证通过！")
else:
    print("存在同月N在P之前的情况，请检查！")