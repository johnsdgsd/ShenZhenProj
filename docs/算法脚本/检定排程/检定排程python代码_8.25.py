import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict, deque
import math

# ============================================================
# 0. 加载码值映射字典
# ============================================================
mapping_file = r"C:\Users\H5966\Desktop\检定排程\码值映射字典.xlsx"
df_detect_equip_type = pd.read_excel(mapping_file, sheet_name='VW_DETECT_EQUIP_TYPE')
df_device_type = pd.read_excel(mapping_file, sheet_name='VW_DEVICE_TYPE')
df_yes_no_flag = pd.read_excel(mapping_file, sheet_name='VW_YES_NO_FLAG')
df_equip_cls = pd.read_excel(mapping_file, sheet_name='VW_EQUIP_CLS')
df_equip_categ = pd.read_excel(mapping_file, sheet_name='VW_EQUIP_CATEG')
df_detect_type = pd.read_excel(mapping_file, sheet_name='VW_DETECT_TYPE')
df_dmd_plan_type = pd.read_excel(mapping_file, sheet_name='VW_DMD_PLAN_TYPE')

# 构建编码↔名称双向映射
detect_equip_type_code_to_name = {int(row['编码']): str(row['名称']) for _, row in df_detect_equip_type.iterrows()}
detect_equip_type_name_to_code = {str(row['名称']): int(row['编码']) for _, row in df_detect_equip_type.iterrows()}
device_type_code_to_name = {int(row['编码']): str(row['名称']) for _, row in df_device_type.iterrows()}
device_type_name_to_code = {str(row['名称']): int(row['编码']) for _, row in df_device_type.iterrows()}
equip_cls_code_to_name = {int(row['编码']): str(row['名称']) for _, row in df_equip_cls.iterrows()}
equip_cls_name_to_code = {str(row['名称']): int(row['编码']) for _, row in df_equip_cls.iterrows()}
equip_categ_code_to_name = {int(row['编码']): str(row['名称']) for _, row in df_equip_categ.iterrows()}
equip_categ_name_to_code = {str(row['名称']): int(row['编码']) for _, row in df_equip_categ.iterrows()}
detect_type_code_to_name = {int(row['编码']): str(row['名称']) for _, row in df_detect_type.iterrows()}
detect_type_name_to_code = {str(row['名称']): int(row['编码']) for _, row in df_detect_type.iterrows()}
dmd_plan_type_code_to_name = {int(row['编码']): str(row['名称']) for _, row in df_dmd_plan_type.iterrows()}

# 业务分类名称 → VW_DETECT_EQUIP_TYPE 编码（用于 parse_device_category 和 dev_code_to_cat 的统一编码体系）
CAT_NAME_TO_DETECT_CODE = {
    '单相电能表': 1,
    '三相电能表': 2,  # 默认→三相直接表
    '三相直接表': 2,
    '三相互感表': 3,
    '10kV电压互感器': 4,
    '20kV电压互感器': 5,
    '10kV电流互感器': 6,
    '20kV电流互感器': 7,
    '低压电流互感器': 8,
    '低压电流互感器_大变比': 9,
    '低压电流互感器_DBI': 10,
    '智能量测终端': 14,
    '负荷管理终端': 14,
    '负荷控制终端': 14,
    '集中器': 14,
    '配变监测计量终端': 14,
    '配变监测终端': 14,
    '厂站终端': 14,
}

# 业务分类名称 → VW_EQUIP_CLS 编码
CAT_NAME_TO_EQUIP_CLS_CODE = {
    '单相电能表': 1,
    '三相电能表': 2,
    '三相直接表': 2,
    '三相互感表': 2,
    '负荷管理终端': 3,
    '负荷控制终端': 3,
    '集中器': 4,
    '配变监测计量终端': 5,
    '配变监测终端': 5,
    '10kV电流互感器': 6,
    '10kV电压互感器': 7,
    '低压电流互感器': 8,
    '低压电流互感器_大变比': 8,
    '低压电流互感器_DBI': 8,
    '智能量测终端': 19,
    '20kV电流互感器': 20,
    '20kV电压互感器': 21,
    '厂站终端': 10,
}

# 业务分类名称 → VW_EQUIP_CATEG 编码
def get_equip_categ_code(cat_name):
    """根据设备分类名称推导设备类别编码"""
    if any(k in cat_name for k in ['电能表', '直接表', '互感表']):
        return 1  # 电能表
    if any(k in cat_name for k in ['电压互感器', '电流互感器', '低压电流互感器']):
        return 2  # 互感器
    if any(k in cat_name for k in ['终端', '集中器', '负荷']):
        return 9  # 计量自动化终端
    return None

# 仓类型名称 → VW_DEVICE_TYPE 编码
CHAMBER_TYPE_NAME_TO_CODE = {
    '单相电能表检定仓': 1,
    '单三相兼容检定仓': 2,
    '终端检定仓': 3,
    '三相电能表检定仓': 4,
    '三相表兼容终端检定仓': 5,
    '10kv/20kv电压兼容仓': 6,
    '10kv/20kv电流兼容仓': 7,
    '普通/大变比低压CT兼容仓': 8,
    '普通/DBI低压CT兼容仓': 9,
}

# 默认检定类型：首次检定（编码 3）
DEFAULT_DETECT_TYPE_CODE = 3
# 抽检检定类型：到货后抽样检测（编码 2）
SAMPLING_DETECT_TYPE_CODE = 2
# 默认需求计划类型：月计划（编码 1）
DEFAULT_DMD_PLAN_TYPE_CODE = 1

print("码值映射字典加载完成。")
print(f"  VW_DETECT_EQUIP_TYPE: {len(detect_equip_type_code_to_name)} 条")
print(f"  VW_DEVICE_TYPE: {len(device_type_code_to_name)} 条")
print(f"  VW_EQUIP_CLS: {len(equip_cls_code_to_name)} 条")
print(f"  VW_EQUIP_CATEG: {len(equip_categ_code_to_name)} 条")
print(f"  VW_DETECT_TYPE: {len(detect_type_code_to_name)} 条")
print(f"  VW_DMD_PLAN_TYPE: {len(dmd_plan_type_code_to_name)} 条")

# ============================================================
# 1. 读取原始数据
# ============================================================
file_path = r"C:\Users\H5966\Desktop\检定排程\检定仓情况-20260825.xlsx"

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

# 2.3. 构建非需求设备目标设备类型映射
non_demand_target_config = defaultdict(list)
for _, row in df_non_demand_target.iterrows():
    original_code = str(row['设备类型码大码'])
    target_code = str(row['目标设备类型码'])
    percentage = float(row['分配比例（%）'])
    non_demand_target_config[original_code].append((target_code, percentage))
if non_demand_target_config:
    print(f"非需求设备目标类型映射: {dict(non_demand_target_config)}")

# 2.4. 构建需求设备目标设备类型映射
big_code_to_demand_targets = {}
for _, row in df_demand.iterrows():
    big_code = str(row['设备类型码大码'])
    small_code = str(row['设备码'])
    qty = int(row['申请数量'])
    if big_code not in big_code_to_demand_targets:
        big_code_to_demand_targets[big_code] = defaultdict(int)
    big_code_to_demand_targets[big_code][small_code] += qty
big_code_target_proportions = {}
for big_code, small_counts in big_code_to_demand_targets.items():
    total = sum(small_counts.values())
    big_code_target_proportions[big_code] = [(sc, cnt / total) for sc, cnt in small_counts.items()]
if big_code_target_proportions:
    print(f"需求设备目标类型比例映射: {dict(big_code_target_proportions)}")

# 2.2. 构建低压电流互感器子类型映射
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

# 2. 构建基础映射（使用 VW_DETECT_EQUIP_TYPE 编码）
dev_code_to_cat = {}  # 设备码 → VW_DETECT_EQUIP_TYPE 编码
dev_code_to_cat_name = {}  # 设备码 → 设备分类名称（中文）
dev_code_to_access = {}
dev_code_to_detect_scheme_id = {}  # 设备码 → detectSchemeId（参数标识）
for _, row in df_spec.iterrows():
    code = row['设备码']
    cat = row['设备分类']
    access = row['接入方式'] if pd.notna(row['接入方式']) else ''
    # 低压电流互感器使用子类型分类
    if cat == '低压电流互感器':
        cat = dev_code_to_low_voltage_subtype.get(str(code), cat)
    detect_code = CAT_NAME_TO_DETECT_CODE.get(cat, None)
    dev_code_to_cat[code] = detect_code if detect_code is not None else cat
    dev_code_to_cat_name[code] = cat
    dev_code_to_access[code] = access
    # 读取参数标识作为detectSchemeId
    if pd.notna(row['参数标识']):
        dev_code_to_detect_scheme_id[code] = int(row['参数标识'])

if dev_code_to_detect_scheme_id:
    print(f"detectSchemeId映射: {len(dev_code_to_detect_scheme_id)} 条设备码映射")

df_overall[['线体编号', '线体名称', '检定仓类型', '检定仓编号']] = df_overall[['线体编号', '线体名称', '检定仓类型', '检定仓编号']].ffill()
df_overall['所检设备表类型'] = df_overall['所检设备表类型'].astype(str).str.replace('\n', ' ', regex=False)


def parse_device_category(desc):
    """解析设备描述 → VW_DETECT_EQUIP_TYPE 编码"""
    desc = desc.lower()
    if '单相电能表' in desc:
        return 1  # 单相电能表
    elif '三相直接表' in desc:
        return 2  # 三相直接表
    elif '三相互感表' in desc or '三相互感电能表' in desc:
        return 3  # 三相互感表
    elif '集中器' in desc or '负荷控制终端' in desc or '配变监测终端' in desc or '智能量测终端' in desc or '厂站终端' in desc:
        return 14  # 智能量测终端（经互感器接入）
    elif '10kv电压互感器' in desc:
        return 4  # 10kV电压互感器
    elif '20kv电压互感器' in desc:
        return 5  # 20kV电压互感器
    elif '10kv电流互感器' in desc:
        return 6  # 10kV电流互感器
    elif '20kv电流互感器' in desc:
        return 7  # 20kV电流互感器
    elif '大变比型低压电流互感器' in desc:
        return 9  # 大变比型低压电流互感器
    elif 'dbi型低压电流互感器' in desc:
        return 10  # DBI型低压电流互感器
    elif '普通型低压电流互感器' in desc:
        return 8  # 普通型低压电流互感器
    else:
        return None


def get_detect_equip_type_name(code):
    """VW_DETECT_EQUIP_TYPE 编码 → 名称"""
    return detect_equip_type_code_to_name.get(code, str(code))


def get_equip_cls_code(cat_name):
    """设备分类名称 → VW_EQUIP_CLS 编码"""
    return CAT_NAME_TO_EQUIP_CLS_CODE.get(cat_name, None)


def get_equip_cls_name(code):
    """VW_EQUIP_CLS 编码 → 名称"""
    return equip_cls_code_to_name.get(code, str(code))


def get_device_type_code(type_name):
    """仓类型名称 → VW_DEVICE_TYPE 编码"""
    return CHAMBER_TYPE_NAME_TO_CODE.get(type_name, None)


def get_device_type_name(code):
    """VW_DEVICE_TYPE 编码 → 名称"""
    return device_type_code_to_name.get(code, str(code))


def get_detect_scheme_id(dev_code):
    """根据设备码获取detectSchemeId（参数标识），自动尝试大小码匹配"""
    if dev_code in dev_code_to_detect_scheme_id:
        return dev_code_to_detect_scheme_id[dev_code]
    big_code = dev_code_to_big_code.get(dev_code, dev_code)
    if big_code in dev_code_to_detect_scheme_id:
        return dev_code_to_detect_scheme_id[big_code]
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

# 3. 设备检定时间（使用 VW_DETECT_EQUIP_TYPE 编码）
spec_time = {}
for _, row in df_spec.iterrows():
    cat = row['设备分类']
    detect_code = CAT_NAME_TO_DETECT_CODE.get(cat, None)
    if detect_code is not None and pd.notna(row['自动检定时间']):
        spec_time[detect_code] = int(row['自动检定时间'])
default_times = {
    2: 414,  # 三相电能表（三相直接表）
    3: 414,  # 三相互感表
    1: 108,  # 单相电能表
    14: 414,  # 智能量测终端
    4: 25,  # 10kV电压互感器
    5: 30,  # 20kV电压互感器
    6: 25,  # 10kV电流互感器
    7: 30,  # 20kV电流互感器
    8: 25,  # 低压电流互感器
    9: 25,  # 低压电流互感器_大变比
    10: 25,  # 低压电流互感器_DBI
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
# 【甲方20260825新需求】解析"是否已抽检"标志与"抽检数量"
#   是否已抽检=否 的批次，需先按抽检数量做抽检（到货后抽样检测），抽检完成后才能做首检
pending_batches = deque()
batch_sample_info = {}  # batch_no -> {'sampled': bool(True表示已抽检), 'sample_qty': int}


def _parse_sampled(val):
    """把"是否已抽检"转为布尔值：是→已抽检(True)，否/0→未抽检(False)，空值默认视为已抽检"""
    if pd.isna(val):
        return True
    s = str(val).strip()
    if s in ('否', '0', '0.0', 'False', 'false', ''):
        return False
    return True


def _safe_int(val, default=0):
    if pd.isna(val):
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


for _, row in df_unqualified.iterrows():
    batch_no = row['到货批次号']
    dev_code = row['设备类型码']
    qty = int(row['可检库存'])
    est_date = datetime(2026, 1, 1, 0, 0, 0)
    pending_batches.append([str(batch_no), dev_code, qty, qty, est_date])
    bn = str(batch_no)
    batch_sample_info[bn] = {
        'sampled': _parse_sampled(row['是否已抽检']),
        'sample_qty': _safe_int(row['抽检数量'], 0),
    }

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
    bn = str(batch_no)
    batch_sample_info[bn] = {
        'sampled': _parse_sampled(row['是否已抽检']),
        'sample_qty': _safe_int(row['抽检数量'], 0),
    }

pending_batches = deque(sorted(pending_batches, key=lambda x: (x[4], x[0])))
print(f"待处理批次总数: {len(pending_batches)}")

need_sampling_batches = [bn for bn, info in batch_sample_info.items() if not info['sampled'] and info['sample_qty'] > 0]
print(f"需安排抽检的批次: {len(need_sampling_batches)} 个")
for bn in need_sampling_batches:
    info = batch_sample_info[bn]
    print(f"  {bn}: 抽检数量 {info['sample_qty']}")

# 7. 解析需求明细
for _, row in df_demand.iterrows():
    dev_code = row['设备类型码大码']
    dev_cat_from_demand = row['设备分类'] if pd.notna(row['设备分类']) else ''
    if dev_cat_from_demand and dev_code not in dev_code_to_cat:
        if dev_cat_from_demand == '低压电流互感器':
            dev_cat_from_demand = dev_code_to_low_voltage_subtype.get(str(dev_code), dev_cat_from_demand)
        detect_code = CAT_NAME_TO_DETECT_CODE.get(dev_cat_from_demand, None)
        dev_code_to_cat[dev_code] = detect_code if detect_code is not None else dev_cat_from_demand

demand_by_month = defaultdict(list)
for _, row in df_demand.iterrows():
    month = str(row['所属月份'])
    dev_code = row['设备类型码大码']
    qty = int(row['申请数量'])
    demand_by_month[month].append((dev_code, qty))
months = sorted(demand_by_month.keys())

# 8. 设备类型优先级（使用 VW_DETECT_EQUIP_TYPE 编码）
def get_priority(dev_code):
    cat = dev_code_to_cat.get(dev_code, 0)
    if cat == 14:  # 智能量测终端
        return 0
    elif cat == 2 or cat == 3:  # 三相电能表
        return 1
    elif cat == 1:  # 单相电能表
        return 2
    else:
        return 3


# 9. 时间计算辅助函数
MAX_DAY_SEARCH = 365 * 10
MAX_WORK_DATE = datetime(2026, 4, 30).date()


def is_workday(day):
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


# 10. 时间计算函数（支持加班）
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
            # 甲方20260825新需求：抽检完成后首检需精确到分钟衔接。
            # 直接推进到 earliest 时刻：若 earliest 落在工作日工作时段之前
            # （如到货日期 00:00），后续循环会自动上取整到当日工作开始时间；
            # 若 earliest 为非工作日，则顺延到下一工作日。
            candidate_min = int((earliest_abs - base_date).total_seconds() / 60)
            continue

        return int((start_abs - base_date).total_seconds() / 60)

    raise OverflowError(f"时间计算超过 {MAX_DAY_SEARCH} 天仍未找到合适时段，请检查排程配置。")


# 11. 核心排程函数
chamber_time = {ch: 0 for ch in chambers.keys()}
schedule_details = []
sampling_done_batches = set()  # 已安排过抽检的批次号（每个批次只抽检一次）
batch_sample_end = {}  # batch_no -> 抽检完成分钟数；供同批次多次调度时约束首检不得早于抽检完成


def schedule_sampling(batch_no, dev_code, sample_qty, month, is_priority, earliest_start=0):
    """甲方新需求：对未抽检批次先安排抽检（到货后抽样检测，编码2）。
    抽检不产生合格品库存，仅作为首检前的质量把关步骤。
    返回抽检完成后的分钟数，作为后续首检的最早开始时间。"""
    if sample_qty <= 0:
        return earliest_start
    dev_cat = dev_code_to_cat.get(dev_code)
    if dev_cat is None:
        return earliest_start

    available = []
    for ch, info in chambers.items():
        cap = info['capacity'].get(dev_cat)
        if cap and cap > 0:
            if dev_cat == 14 and chamber_type_id_map.get(ch, 0) == 5:
                access = dev_code_to_access.get(dev_code, '')
                if '经互感' not in access:
                    continue
            available.append((ch, cap))
    if not available:
        return earliest_start
    available.sort(key=lambda x: (chamber_time[x[0]], -chambers[x[0]]['dev_count'], -x[0][0]))

    cat_name = dev_code_to_cat_name.get(dev_code, get_detect_equip_type_name(dev_cat))
    equip_cls_code = get_equip_cls_code(cat_name)
    equip_categ_code = get_equip_categ_code(cat_name)

    remaining = sample_qty
    sub_counter = 1
    last_end_min = earliest_start
    while remaining > 0:
        available.sort(key=lambda x: (chamber_time[x[0]], -chambers[x[0]]['dev_count'], -x[0][0]))
        ch, max_cap = available[0]
        batch_qty = min(remaining, max_cap)
        duration = spec_time[dev_cat]
        line_id = ch[0]
        start_min = get_next_start_minutes(chamber_time[ch], duration, line_id, earliest_start)
        end_min = start_min + duration
        start_time = base_date + timedelta(minutes=start_min)
        end_time = base_date + timedelta(minutes=end_min)
        internal_batch = f"{month}-{batch_no}-S-{sub_counter}"

        chamber_type_name = chambers[ch]['type_name']
        device_type_code = get_device_type_code(chamber_type_name)
        detect_scheme_id = get_detect_scheme_id(dev_code)

        schedule_details.append({
            '月份': month,
            '检定线ID': ch[0],
            '检定线名称': line_name_map.get(ch[0], ''),
            '检定仓编号': ch[1],
            '检定仓类型': chamber_type_name,
            '检定仓类型编码': device_type_code,
            '检定仓类型名称': chamber_type_name,
            '检定设备类型编码': dev_cat,
            '检定设备类型名称': get_detect_equip_type_name(dev_cat),
            '设备类型': get_detect_equip_type_name(dev_cat),
            '设备分类编码': equip_cls_code,
            '设备分类名称': get_equip_cls_name(equip_cls_code) if equip_cls_code else '',
            '设备类别编码': equip_categ_code,
            '设备类别名称': equip_categ_code_to_name.get(equip_categ_code, '') if equip_categ_code else '',
            '设备码': dev_code,
            '目标设备类型码': dev_code,
            '到货批次号': batch_no,
            '是否为需求优先': 1 if is_priority else 0,
            '需求计划类型编码': DEFAULT_DMD_PLAN_TYPE_CODE,
            '需求计划类型名称': dmd_plan_type_code_to_name.get(DEFAULT_DMD_PLAN_TYPE_CODE, ''),
            '检定类型编码': SAMPLING_DETECT_TYPE_CODE,
            '检定类型名称': detect_type_code_to_name.get(SAMPLING_DETECT_TYPE_CODE, '到货后抽样检测'),
            'detectSchemeId': detect_scheme_id if detect_scheme_id is not None else '',
            '内部批次号': internal_batch,
            '每批数量': batch_qty,
            '预计开始时间': start_time,
            '预计完成时间': end_time,
            '检定时长(天)': round(duration / 1440, 1),
            '检定时长(分钟/批)': duration
        })
        chamber_time[ch] = end_min
        last_end_min = end_min
        remaining -= batch_qty
        available[0] = (ch, max_cap)
        sub_counter += 1
    return last_end_min


def schedule_batch(batch_no, dev_code, quantity, is_priority, month, earliest_start=0, target_dev_code=None):
    # 甲方新需求：批次未抽检则先安排抽检，抽检完成后再做首检（每个批次只抽检一次）
    if batch_no not in sampling_done_batches:
        binfo = batch_sample_info.get(batch_no)
        sampling_done_batches.add(batch_no)
        if binfo is not None and not binfo['sampled'] and binfo['sample_qty'] > 0:
            sample_end = schedule_sampling(batch_no, dev_code, binfo['sample_qty'], month, is_priority, earliest_start)
            if sample_end > earliest_start:
                earliest_start = sample_end
            batch_sample_end[batch_no] = sample_end
    # 同批次可能被拆分为多次调度（多目标设备类型/跨月），抽检完成时间需对每次首检都生效
    if batch_no in batch_sample_end and batch_sample_end[batch_no] > earliest_start:
        earliest_start = batch_sample_end[batch_no]
    if quantity <= 0:
        return 0
    dev_cat = dev_code_to_cat.get(dev_code)
    if dev_cat is None:
        raise ValueError(f"设备码 {dev_code} 无法映射到设备分类")
    if target_dev_code is None:
        target_dev_code = dev_code
    available = []
    for ch, info in chambers.items():
        cap = info['capacity'].get(dev_cat)
        if cap and cap > 0:
            # 智能量测终端(编码14) 在三相表兼容终端检定仓(仓类型ID=5)时，仅允许经互感器接入
            if dev_cat == 14 and chamber_type_id_map.get(ch, 0) == 5:
                access = dev_code_to_access.get(dev_code, '')
                if '经互感' not in access:
                    continue
            available.append((ch, cap))
    if not available:
        raise ValueError(f"没有支持设备类型 {get_detect_equip_type_name(dev_cat)} 的检定仓！")

    if is_priority and dev_cat == 1:
        available.sort(key=lambda x: (chamber_time[x[0]], -chambers[x[0]]['dev_count'], -x[0][0]))
    elif is_priority:
        available.sort(key=lambda x: (chamber_time[x[0]], chambers[x[0]]['dev_count'], -x[0][0]))
    else:
        available.sort(key=lambda x: (chamber_time[x[0]], -chambers[x[0]]['dev_count'], -x[0][0]))

    remaining = quantity
    sub_counter = 1

    # 获取设备分类名称（用于输出）
    cat_name = dev_code_to_cat_name.get(dev_code, get_detect_equip_type_name(dev_cat))
    equip_cls_code = get_equip_cls_code(cat_name)
    equip_categ_code = get_equip_categ_code(cat_name)

    while remaining > 0:
        if is_priority and dev_cat == 1:
            available.sort(key=lambda x: (chamber_time[x[0]], -chambers[x[0]]['dev_count'], -x[0][0]))
        elif is_priority:
            available.sort(key=lambda x: (chamber_time[x[0]], chambers[x[0]]['dev_count'], -x[0][0]))
        else:
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

        # 仓类型编码
        chamber_type_name = chambers[ch]['type_name']
        device_type_code = get_device_type_code(chamber_type_name)

        # detectSchemeId：从规格设备码信息表的参数标识获取
        detect_scheme_id = get_detect_scheme_id(dev_code)

        schedule_details.append({
            '月份': month,
            '检定线ID': ch[0],
            '检定线名称': line_name_map.get(ch[0], ''),
            '检定仓编号': ch[1],
            '检定仓类型': chamber_type_name,
            '检定仓类型编码': device_type_code,
            '检定仓类型名称': chamber_type_name,
            '检定设备类型编码': dev_cat,
            '检定设备类型名称': get_detect_equip_type_name(dev_cat),
            '设备类型': get_detect_equip_type_name(dev_cat),
            '设备分类编码': equip_cls_code,
            '设备分类名称': get_equip_cls_name(equip_cls_code) if equip_cls_code else '',
            '设备类别编码': equip_categ_code,
            '设备类别名称': equip_categ_code_to_name.get(equip_categ_code, '') if equip_categ_code else '',
            '设备码': dev_code,
            '目标设备类型码': target_dev_code,
            '到货批次号': batch_no,
            '是否为需求优先': 1 if is_priority else 0,
            '需求计划类型编码': DEFAULT_DMD_PLAN_TYPE_CODE,
            '需求计划类型名称': dmd_plan_type_code_to_name.get(DEFAULT_DMD_PLAN_TYPE_CODE, ''),
            '检定类型编码': DEFAULT_DETECT_TYPE_CODE,
            '检定类型名称': detect_type_code_to_name.get(DEFAULT_DETECT_TYPE_CODE, ''),
            'detectSchemeId': detect_scheme_id if detect_scheme_id is not None else '',
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


def get_batch_last_p_end_minutes(batch_no):
    max_end = 0
    for item in schedule_details:
        if item['到货批次号'] == batch_no and item['是否为需求优先'] == 1:
            end_min = int((item['预计完成时间'] - base_date).total_seconds() / 60)
            if end_min > max_end:
                max_end = end_min
    return max_end


def schedule_non_demand_batch(batch_no, dev_code, quantity, month, earliest_start):
    targets = non_demand_target_config.get(dev_code, [(dev_code, 100)])
    dev_cat = dev_code_to_cat.get(dev_code, 0)
    if dev_cat == 1:  # 单相电能表
        big_code = dev_code_to_big_code.get(dev_code, dev_code)
        if big_code != dev_code:
            small_code = dev_code
        else:
            targets_list = big_code_target_proportions.get(dev_code, [(dev_code, 1.0)])
            small_code = targets_list[0][0]
    else:
        big_code = dev_code
        small_code = dev_code
    if len(targets) == 1 and targets[0][1] == 100 and targets[0][0] == dev_code:
        if dev_cat == 1:
            return schedule_batch(batch_no, big_code, quantity, is_priority=False, month=month, earliest_start=earliest_start, target_dev_code=small_code)
        else:
            return schedule_batch(batch_no, dev_code, quantity, is_priority=False, month=month, earliest_start=earliest_start, target_dev_code=dev_code)
    total_pct = sum(pct for _, pct in targets)
    scheduled = 0
    for idx, (target_code, pct) in enumerate(targets):
        if idx == len(targets) - 1:
            target_qty = quantity - scheduled
        else:
            target_qty = int(quantity * pct / total_pct)
        if target_qty > 0:
            if dev_cat == 1:
                scheduled += schedule_batch(batch_no, big_code, target_qty, is_priority=False,
                                            month=month, earliest_start=earliest_start, target_dev_code=small_code)
            else:
                scheduled += schedule_batch(batch_no, target_code, target_qty, is_priority=False,
                                            month=month, earliest_start=earliest_start, target_dev_code=target_code)
    return scheduled


# 12. 按月排程
for month in months:
    demand_dict = defaultdict(int)
    for dev_code, qty in demand_by_month[month]:
        demand_dict[dev_code] += qty

    sorted_dev_codes = sorted(demand_dict.keys(), key=lambda x: (get_priority(x), '20kV' not in dev_code_to_cat_name.get(x, '')))

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

            if remain >= deficit:
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
                target_props = big_code_target_proportions.get(dev_code, [(dev_code, 1.0)])
                if len(target_props) == 1:
                    schedule_batch(batch_no, dev_code, demand_take, is_priority=True, month=month, earliest_start=est_minutes, target_dev_code=target_props[0][0])
                else:
                    total_pct = sum(pct for _, pct in target_props)
                    scheduled = 0
                    for idx, (small_code, pct) in enumerate(target_props):
                        if idx == len(target_props) - 1:
                            small_qty = demand_take - scheduled
                        else:
                            small_qty = int(demand_take * pct / total_pct)
                        if small_qty > 0:
                            scheduled += schedule_batch(batch_no, dev_code, small_qty, is_priority=True, month=month, earliest_start=est_minutes, target_dev_code=small_code)

            if stock_take > 0:
                est_minutes = int((est_date - base_date).total_seconds() / 60) if pd.notna(est_date) else 0
                schedule_non_demand_batch(batch_no, dev_code, stock_take, month, earliest_start=est_minutes)

            if total_take == remain:
                pending_batches.popleft()
            else:
                pending_batches[0][2] -= total_take
            deficit -= demand_take

        original_deficit = need - avail
        inventory[dev_code] = max(0, inventory[dev_code] - original_deficit)

    # 12.5. 处理剩余批次
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
            print(f"警告: 批次 {batch_no} 类型 {get_detect_equip_type_name(dev_cat)} 无对应检定仓，跳过")
            continue

        future_need = future_demand.get(dev_code, 0)
        if future_need >= remain:
            new_pending.append(batch)
        elif future_need > 0:
            excess = remain - future_need
            est_minutes = int((est_date - base_date).total_seconds() / 60) if pd.notna(est_date) else 0
            batch_p_end = get_batch_last_p_end_minutes(batch_no)
            if batch_p_end > est_minutes:
                est_minutes = batch_p_end
            schedule_non_demand_batch(batch_no, dev_code, excess, month, earliest_start=est_minutes)
            batch[2] = future_need
            new_pending.append(batch)
        else:
            est_minutes = int((est_date - base_date).total_seconds() / 60) if pd.notna(est_date) else 0
            batch_p_end = get_batch_last_p_end_minutes(batch_no)
            if batch_p_end > est_minutes:
                est_minutes = batch_p_end
            schedule_non_demand_batch(batch_no, dev_code, remain, month, earliest_start=est_minutes)

    pending_batches = deque(sorted(new_pending, key=lambda x: (x[4], x[0])))

# 12.6. 所有月份处理完毕后，处理剩余批次
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
            print(f"警告: 批次 {batch_no} 类型 {get_detect_equip_type_name(dev_cat)} 无对应检定仓，跳过")
            pending_batches.popleft()
            continue
        est_minutes = int((est_date - base_date).total_seconds() / 60) if pd.notna(est_date) else 0
        batch_p_end = get_batch_last_p_end_minutes(batch_no)
        if batch_p_end > est_minutes:
            est_minutes = batch_p_end
        schedule_non_demand_batch(batch_no, dev_code, remain, last_month, earliest_start=est_minutes)
        pending_batches.popleft()

# 13. 输出结果
df_details = pd.DataFrame(schedule_details)

# 确保字符串列不被科学计数法显示
def convert_dev_code_to_str(df):
    if '设备码' in df.columns:
        df['设备码'] = df['设备码'].astype(str)
    if '目标设备类型码' in df.columns:
        df['目标设备类型码'] = df['目标设备类型码'].astype(str)
    return df

df_details = convert_dev_code_to_str(df_details)

df_schedule_summary = df_details.groupby(
    ['月份', '检定线ID', '检定线名称', '检定设备类型编码', '检定设备类型名称',
     '设备码', '到货批次号', '是否为需求优先', '检定类型编码', '检定类型名称']
).agg(
    总检定数量=('每批数量', 'sum'),
    批次数=('内部批次号', 'nunique')
).reset_index()

df_details_sorted = df_details.sort_values(['预计开始时间', '检定线ID'])

df_util = df_details.groupby(
    ['月份', '检定线ID', '检定线名称', '检定仓编号', '检定仓类型', '检定仓类型编码']
).agg(
    总批次数=('内部批次号', 'nunique'),
    总检定量=('每批数量', 'sum')
).reset_index()

df_batch_alloc = df_details.groupby(
    ['月份', '到货批次号', '检定设备类型编码', '检定设备类型名称', '设备码', '是否为需求优先', '检定类型编码', '检定类型名称']
).agg(
    分配数量=('每批数量', 'sum')
).reset_index()
df_batch_alloc['检定时长(分钟/批)'] = df_batch_alloc['检定设备类型编码'].map(spec_time)

arrival_set = set()
for _, row in df_arrival.iterrows():
    if pd.notna(row['到货批次号']):
        arrival_set.add((str(row['到货批次号']), row['设备分类'], row['设备规格'], int(row['数量'])))
for _, row in df_unqualified.iterrows():
    if pd.notna(row['到货批次号']):
        arrival_set.add((str(row['到货批次号']), row['设备分类'], row['设备类型码'], int(row['可检库存'])))
original_arrivals = []
for batch_no, dev_cat, dev_code, qty in arrival_set:
    detect_code = CAT_NAME_TO_DETECT_CODE.get(dev_cat, None)
    original_arrivals.append({
        '到货批次号': batch_no,
        '设备类型': dev_cat,
        '检定设备类型编码': detect_code,
        '检定设备类型名称': get_detect_equip_type_name(detect_code) if detect_code else dev_cat,
        '设备码': dev_code,
        '原始到货量': qty,
        '检定时长(分钟/批)': spec_time.get(detect_code, 414) if detect_code else 414
    })
df_original = pd.DataFrame(original_arrivals).drop_duplicates(subset=['到货批次号'])

demand_summary = []
for month, demands in demand_by_month.items():
    for dev_code, qty in demands:
        dev_cat = dev_code_to_cat.get(dev_code, 0)
        cat_name = dev_code_to_cat_name.get(dev_code, get_detect_equip_type_name(dev_cat))
        equip_cls_code = get_equip_cls_code(cat_name)
        equip_categ_code = get_equip_categ_code(cat_name)
        demand_summary.append({
            '月份': month,
            '设备码': dev_code,
            '检定设备类型编码': dev_cat,
            '检定设备类型名称': get_detect_equip_type_name(dev_cat),
            '设备分类编码': equip_cls_code,
            '设备分类名称': get_equip_cls_name(equip_cls_code) if equip_cls_code else '',
            '设备类别编码': equip_categ_code,
            '设备类别名称': equip_categ_code_to_name.get(equip_categ_code, '') if equip_categ_code else '',
            '需求数量': qty,
            '需求计划类型编码': DEFAULT_DMD_PLAN_TYPE_CODE,
            '需求计划类型名称': dmd_plan_type_code_to_name.get(DEFAULT_DMD_PLAN_TYPE_CODE, ''),
        })
df_demand_summary = pd.DataFrame(demand_summary)

chamber_config_rows = []
for (line_id, chamber_id), info in chambers.items():
    line_name = line_name_map.get(line_id, '')
    max_cap = max(info['capacity'].values()) if info['capacity'] else 0
    type_name = info['type_name']
    device_type_code = get_device_type_code(type_name)
    chamber_config_rows.append({
        '检定线ID': line_id,
        '检定线名称': line_name,
        '检定仓编号': chamber_id,
        '仓类型': type_name,
        '检定仓类型编码': device_type_code,
        '检定仓类型名称': type_name,
        '每仓最大容量': max_cap
    })
df_chamber_config_output = pd.DataFrame(chamber_config_rows)

df_schedule_summary = convert_dev_code_to_str(df_schedule_summary)
df_details_sorted = convert_dev_code_to_str(df_details_sorted)
df_batch_alloc = convert_dev_code_to_str(df_batch_alloc)
df_original = convert_dev_code_to_str(df_original)
df_demand_summary = convert_dev_code_to_str(df_demand_summary)

# 写入Excel
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
for cat_code in [5, 7]:  # 5=20kV电压互感器, 7=20kV电流互感器
    cat_name = get_detect_equip_type_name(cat_code)
    subset = df_details[df_details['检定设备类型编码'] == cat_code]
    if len(subset) > 0:
        print(f"{cat_name}(编码{cat_code}): 共{len(subset)}条记录, 总计{subset['每批数量'].sum()}台, "
              f"每批最大{subset['每批数量'].max()}, 每批最小{subset['每批数量'].min()}")
        for _, row in subset.iterrows():
            print(f"  仓:{row['检定仓编号']}, 批:{row['每批数量']}, 时间:{row['预计开始时间']}~{row['预计完成时间']}")
    else:
        print(f"{cat_name}(编码{cat_code}): 无排程记录！")

print("\n=== 关键验证：低压电流互感器子类型 ===")
for cat_code in [8, 9, 10]:
    cat_name = get_detect_equip_type_name(cat_code)
    subset = df_details[df_details['检定设备类型编码'] == cat_code]
    if len(subset) > 0:
        print(f"{cat_name}(编码{cat_code}): 共{len(subset)}条记录, 总计{subset['每批数量'].sum()}台, "
              f"仓列表: {subset['检定仓编号'].unique()}")
    else:
        print(f"{cat_name}(编码{cat_code}): 无排程记录")

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
n_before_p_found = False
cross_month_n_before_p = []
for batch_no in df_details['到货批次号'].unique():
    batch_data = df_details[df_details['到货批次号'] == batch_no].sort_values('预计开始时间')
    labels = batch_data['是否为需求优先'].tolist()
    months_list = batch_data['月份'].tolist()
    for i in range(len(labels) - 1):
        if labels[i] == 0 and labels[i + 1] == 1:
            if months_list[i] == months_list[i + 1]:
                print(f"!!! 同月异常 - 批次 {batch_no}: 第{i}条是N({batch_data.iloc[i]['预计开始时间']}, 月份{months_list[i]}), 第{i+1}条是P({batch_data.iloc[i+1]['预计开始时间']}, 月份{months_list[i+1]})")
                n_before_p_found = True
            else:
                cross_month_n_before_p.append((batch_no, months_list[i], months_list[i + 1]))
if cross_month_n_before_p:
    print("注意：以下为跨月份N→P顺序（N在前月已排程，P在后月新增需求，属正常跨月行为）：")
    for bn, nm, pm in cross_month_n_before_p:
        print(f"  批次 {bn}: N在月份{nm}, P在月份{pm}")
if not n_before_p_found:
    print("所有批次中同月内N不存在于P之前，验证通过！")
else:
    print("存在同月N在P之前的情况，请检查！")

# 16. 码值映射验证
print("\n" + "=" * 80)
print("=== 码值映射应用验证 ===")
print(f"\nVW_DETECT_EQUIP_TYPE 使用情况: {sorted(df_details['检定设备类型编码'].dropna().unique())}")
print(f"VW_DEVICE_TYPE 使用情况: {sorted(df_details['检定仓类型编码'].dropna().unique())}")
print(f"VW_YES_NO_FLAG: 是(P)=1, 否(N)=0（在'是否为需求优先'列中）")
print(f"VW_DETECT_TYPE: 默认={DEFAULT_DETECT_TYPE_CODE}({detect_type_code_to_name.get(DEFAULT_DETECT_TYPE_CODE, '')})")
print(f"VW_DMD_PLAN_TYPE: 默认={DEFAULT_DMD_PLAN_TYPE_CODE}({dmd_plan_type_code_to_name.get(DEFAULT_DMD_PLAN_TYPE_CODE, '')})")