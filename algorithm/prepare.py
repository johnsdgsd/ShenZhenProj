"""
算法输入准备
============
process_data()：把 data 层读出的 {key: DataFrame} 填充到 scheduler 模块级全局变量。

逻辑与原脚本 `检定排程python代码最新8.03.py` 第 28-224 行逐行一致，
原位置在顶层 main.py，现随算法移入本包，保证 CLI 与 HTTP 两条路径复用。
"""
import logging
from collections import defaultdict, deque
from datetime import datetime

import pandas as pd

from common.utils import clean_columns, parse_device_category
from . import scheduler

logger = logging.getLogger(__name__)


def process_data(dfs, sched_cfg):
    """填充 scheduler 模块级全局变量。

    逻辑与原脚本 `检定排程python代码最新8.03.py` 第 28-224 行逐行一致。
    dfs 来自 data.reader（Excel 或 JSON），列名与算法期望一致。
    """
    # 列名清洗（去空格）
    for key in dfs:
        dfs[key] = clean_columns(dfs[key])

    df_spec = dfs['spec']
    df_overall = dfs['overall']
    df_chamber_config = dfs['chamber_config']
    df_chamber_type = dfs['chamber_type']
    df_line_info = dfs['line_info']
    df_time_config = dfs['time_config']
    df_gap_config = dfs['gap_config']
    df_qualified = dfs['qualified']
    df_unqualified = dfs['unqualified']
    df_arrival = dfs['arrival']
    df_demand = dfs['demand']

    logger.info("===== 数据准备开始 =====")
    logger.info("输入规模：spec=%d行 整体情况=%d行 仓配置=%d行 线体=%d行 时间配置=%d行 "
                "间隔配置=%d行 合格库存=%d行 非合格库存=%d行 到货=%d行 需求=%d行",
                len(df_spec), len(df_overall), len(df_chamber_config), len(df_line_info),
                len(df_time_config), len(df_gap_config), len(df_qualified),
                len(df_unqualified), len(df_arrival), len(df_demand))

    # ---- 设备码映射 ----
    dev_code_to_cat = {}
    dev_code_to_access = {}
    for _, row in df_spec.iterrows():
        code = row['设备码']
        cat = row['设备分类']
        access = row['接入方式'] if pd.notna(row['接入方式']) else ''
        dev_code_to_cat[code] = cat
        dev_code_to_access[code] = access
    logger.info("设备码映射：%d 个设备码", len(dev_code_to_cat))

    # ---- 检定仓解析 ----
    df_overall[['线体编号', '线体名称', '检定仓类型']] = df_overall[['线体编号', '线体名称', '检定仓类型']].ffill()
    df_overall['所检设备表类型'] = df_overall['所检设备表类型'].astype(str).str.replace('\n', ' ', regex=False)

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

    logger.info("检定仓解析：加载 %d 个检定仓，仓类型映射 %d 个", len(chambers), len(chamber_type_id_map))

    # ---- 检定时间配置（含默认值回退）----
    spec_time = {}
    for _, row in df_spec.iterrows():
        cat = row['设备分类']
        if pd.notna(row['自动检定时间']):
            spec_time[cat] = int(row['自动检定时间'])
    for k, v in sched_cfg.default_times.items():
        if k not in spec_time:
            spec_time[k] = v
    logger.info("检定时间配置：%d 个设备分类（含默认值回退），详情 %s", len(spec_time), spec_time)

    # ---- 线体名称映射 ----
    line_name_map = {}
    for _, row in df_line_info.iterrows():
        if pd.notna(row['检定线ID']):
            line_name_map[int(row['检定线ID'])] = str(row['检定线名称']).strip()
    logger.info("线体名称映射：%d 条线体", len(line_name_map))

    # ---- 工作日时间配置 ----
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
    logger.info("工作日时间配置：%d 天", len(time_map))

    # ---- 调度时间间隔（含默认值回退）----
    gap_map = {}
    if not df_gap_config.empty:
        for _, row in df_gap_config.iterrows():
            line_id = int(row['线体编号'])
            gap_sec = int(row['调度时间间隔（秒）'])
            gap_map[line_id] = gap_sec / 60.0
    else:
        for line_id in line_name_map.keys():
            gap_map[line_id] = sched_cfg.default_gap_minutes
    logger.info("调度时间间隔：%d 条线体（分钟）", len(gap_map))

    # ---- 基准日期（含默认值回退）----
    if not df_time_config.empty:
        first_date = df_time_config.iloc[0]['工作日日期']
        if hasattr(first_date, 'date'):
            base_date = datetime(first_date.year, first_date.month, first_date.day, 9, 0, 0)
        else:
            base_date = sched_cfg.default_base_date
    else:
        base_date = sched_cfg.default_base_date
    logger.info("基准日期：%s", base_date)

    # ---- 初始库存（按设备码）----
    inventory = defaultdict(int)
    for _, row in df_qualified.iterrows():
        dev_code = row['设备码']
        qualified = row['合格品库存'] if pd.notna(row['合格品库存']) else 0
        undelivered = row['未配送库存'] if pd.notna(row['未配送库存']) else 0
        safety = row['安全库存'] if pd.notna(row['安全库存']) else 0
        available = qualified - undelivered - safety
        if available > 0:
            inventory[dev_code] += int(available)
    logger.info("初始库存（按设备码）: %s", dict(inventory))

    # ---- 待处理批次（非合格品库存 + 到货计划）----
    pending_batches = deque()
    n_unqualified = 0

    for _, row in df_unqualified.iterrows():
        batch_no = row['到货批次号']
        dev_code = row['设备类型码']
        qty = int(row['可检库存'])
        est_date = datetime(2026, 1, 1, 0, 0, 0)
        pending_batches.append([str(batch_no), dev_code, qty, qty, est_date])
        n_unqualified += 1

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
    logger.info("待处理批次总数: %d（非合格品库存 %d 批 + 到货计划 %d 批）",
                len(pending_batches), n_unqualified, len(pending_batches) - n_unqualified)

    # ---- 月度需求 ----
    demand_by_month = defaultdict(list)  # month -> [(dev_code, qty)]
    for _, row in df_demand.iterrows():
        month = str(row['所属月份'])
        dev_code = row['设备类型码大码']
        qty = int(row['申请数量'])
        demand_by_month[month].append((dev_code, qty))
    months = sorted(demand_by_month.keys())
    logger.info("月度需求：%d 个月份 %s，需求总额 %d 台",
                len(months), months,
                sum(q for v in demand_by_month.values() for _, q in v))

    # ---- 写入 scheduler 模块全局变量 ----
    scheduler.dev_code_to_cat = dev_code_to_cat
    scheduler.dev_code_to_access = dev_code_to_access
    scheduler.chambers = chambers
    scheduler.chamber_type_id_map = chamber_type_id_map
    scheduler.spec_time = spec_time
    scheduler.line_name_map = line_name_map
    scheduler.time_map = time_map
    scheduler.gap_map = gap_map
    scheduler.base_date = base_date
    scheduler.inventory = inventory
    scheduler.pending_batches = pending_batches
    scheduler.demand_by_month = demand_by_month
    scheduler.months = months
    # chamber_time / schedule_details 由 run_scheduling() 内部初始化
