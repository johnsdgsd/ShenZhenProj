"""
核心算法模块
============
从原脚本 `检定排程python代码最新8.03.py` 完整迁移，**核心逻辑零修改**，
仅在执行流程中补充了详细日志（不改变任何计算）。

日志约定：
- INFO    : 批次安排决策、月份/设备级调度流程、主调度起止
- DEBUG   : 每个检定子任务的分配明细（仓、数量、起止时间）

模块级全局变量由 prepare.process_data() 在执行前填充：
    dev_code_to_cat / dev_code_to_access / chambers / chamber_type_id_map /
    spec_time / line_name_map / time_map / gap_map / base_date /
    inventory / pending_batches / demand_by_month / months

运行入口：
    run_scheduling()                       -> 填充 chamber_time / schedule_details
    build_output_dataframes(df_arrival, df_unqualified) -> Dict[str, DataFrame]
"""
import logging
import math
from collections import defaultdict, deque
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ==================================================================
# 模块级共享变量（由 prepare.process_data() 填充）
# ==================================================================

dev_code_to_cat = {}
dev_code_to_access = {}
chambers = {}
chamber_type_id_map = {}
spec_time = {}
line_name_map = {}
time_map = {}
gap_map = {}
base_date = None
inventory = None            # defaultdict(int)
pending_batches = None      # deque()
demand_by_month = None      # defaultdict(list)
months = []

chamber_time = {}
schedule_details = []

MAX_DAY_SEARCH = 365 * 10  # 最大搜索天数，防止死循环


# ==================================================================
# 核心函数（原样迁移，零修改）
# 说明：clean_columns / parse_device_category 已移入 common/utils.py（纯工具方法）
# ==================================================================

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


def schedule_batch(batch_no, dev_code, quantity, is_priority, month, earliest_start=0):
    if quantity <= 0:
        return 0
    dev_cat = dev_code_to_cat.get(dev_code)
    if dev_cat is None:
        raise ValueError(f"设备码 {dev_code} 无法映射到设备分类")
    logger.info("  安排批次 %s | 设备码 %s | 数量 %d | 需求优先=%s | 月份=%s",
                batch_no, dev_code, quantity, is_priority, month)
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
        logger.debug("    子任务 %s：仓 %s 分配 %d 台，%s → %s",
                     internal_batch, ch, batch_qty,
                     start_time.strftime('%Y-%m-%d %H:%M:%S'),
                     end_time.strftime('%Y-%m-%d %H:%M:%S'))
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


# ==================================================================
# 新增封装函数（逻辑与原文件主循环/输出构建完全一致）
# ==================================================================

def run_scheduling():
    """主调度循环（原文件第 390-479 行）。填充 chamber_time 与 schedule_details。"""
    global chamber_time, schedule_details
    chamber_time = {ch: 0 for ch in chambers.keys()}
    schedule_details = []

    logger.info("===== 主调度开始 =====")
    logger.info("月份列表：%s（共 %d 个月）", months, len(months))

    for month in months:
        # 当月需求汇总（按设备码）
        demand_dict = defaultdict(int)
        for dev_code, qty in demand_by_month[month]:
            demand_dict[dev_code] += qty
        logger.info("月份 %s：当月需求 %d 台（%d 个设备码）",
                    month, sum(demand_dict.values()), len(demand_dict))

        # 按优先级排序
        sorted_dev_codes = sorted(demand_dict.keys(), key=lambda x: get_priority(x))

        for dev_code in sorted_dev_codes:
            need = demand_dict[dev_code]
            avail = inventory.get(dev_code, 0)
            logger.info("  设备码 %s：需求 %d 台，可用库存 %d 台", dev_code, need, avail)
            if avail >= need:
                inventory[dev_code] -= need
                logger.info("    库存满足需求，扣减后库存 %d 台", inventory[dev_code])
                continue

            deficit = need - avail
            inventory[dev_code] = 0
            logger.info("    库存不足，缺口 %d 台，开始消耗到货批次", deficit)

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

                logger.info("    使用批次 %s（剩余 %d）：需求取 %d 台 + 备货取 %d 台",
                            batch_no, remain, demand_take, stock_take)

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
                logger.warning("批次 %s 设备码 %s 无对应设备分类，跳过", batch_no, dev_code)
                pending_batches.popleft()
                continue
            # 检查是否支持
            support = False
            for info in chambers.values():
                if dev_cat in info['capacity']:
                    support = True
                    break
            if not support:
                logger.warning("批次 %s 类型 %s 无对应检定仓，跳过", batch_no, dev_cat)
                pending_batches.popleft()
                continue
            est_minutes = int((est_date - base_date).total_seconds() / 60) if pd.notna(est_date) else 0
            schedule_batch(batch_no, dev_code, remain, is_priority=False, month=month, earliest_start=est_minutes)
            pending_batches.popleft()

        logger.info("  月份 %s 处理完成，待处理批次剩余 %d 批", month, len(pending_batches))

    logger.info("===== 主调度结束 =====")
    logger.info("共生成 %d 个子任务，总计 %d 台，剩余未处理批次 %d 批",
                len(schedule_details),
                sum(d['每批数量'] for d in schedule_details),
                len(pending_batches))


def build_output_dataframes(df_arrival, df_unqualified):
    """构建输出 DataFrame（原文件第 482-550 行），返回 key 与 output_sheet_names 对齐的字典。

    参数 df_arrival / df_unqualified 是 prepare.process_data 清洗后的原始输入 DataFrame，
    仅用于"原始到货批次" sheet 的构建。
    """
    df_details = pd.DataFrame(schedule_details)
    if df_details.empty:
        # 无排程明细时构造带标准列名的空表，避免下游 groupby 报 KeyError
        df_details = pd.DataFrame(columns=[
            '月份', '检定线ID', '检定线名称', '检定仓编号', '检定仓类型',
            '设备类型', '设备码', '到货批次号', '是否为需求优先', '内部批次号',
            '每批数量', '预计开始时间', '预计完成时间', '检定时长(天)', '检定时长(分钟/批)',
        ])

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

    return {
        'schedule_summary': df_schedule_summary,
        'details_sorted': df_details_sorted,
        'util': df_util,
        'batch_alloc': df_batch_alloc,
        'original': df_original,
        'demand_summary': df_demand_summary,
        'chamber_config': df_chamber_config_output,
    }
