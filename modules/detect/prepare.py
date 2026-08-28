"""
检定排程 — 算法输入准备
========================
process_data()：把 reader 读出的 12 个 {key: DataFrame} 填充到 scheduler 模块级全局变量。

逻辑与 8.28 脚本 `检定排程python代码_8.28最新.py` 相应段落逐行一致，
零修改迁移（仅补充日志 + 硬编码参数改从 SchedulingConfig 取值，默认值与 8.28 相同）。

8.16 起分类统一以 VW_DETECT_EQUIP_TYPE 码为键：spec.设备分类（中文名）经
CAT_NAME_TO_DETECT_CODE 转码存入 dev_code_to_cat，并新增 dev_code_to_cat_name 存中文名。
8.17 起新增 dev_code_to_detect_scheme_id：读取 spec.参数标识 作为 detectSchemeId
（row.get 兜底旧 Excel 无「参数标识」列的场景，行为等价）。
8.25 起新增 batch_sample_info：解析到货/非合格品批次的 是否已抽检/抽检数量。
8.28 调整：是否已抽检 只认 '是'（接口 sampleFlag 1/0 已在 reader 归一化为 是/否）；
未抽检批次的抽检数量从批次数量中扣除（只抽检、不再首检）；新增 initial_inventory
期初库存快照（供 12.7 需求优先事后校正）。row.get 兜底旧 Excel 无此列的场景。

日志约定：
- INFO    : 各准备步骤规模（输入/映射/仓/时间配置/库存/批次/需求）
- WARNING : 数据问题——无分类设备带 schTime 无法归属、需求设备码无法建立分类映射
- DEBUG   : 数据明细——仓行跳过原因、默认时长/子类型回退、无分类设备码映射为空
"""
import logging
from collections import defaultdict, deque
from datetime import datetime

import pandas as pd

from common.utils import clean_columns
from . import scheduler
from .category import classify_low_voltage_subtype, get_detect_equip_type_name, parse_device_category
from .constants import ACCESS_DIRECT, ACCESS_HUGAN, ACCESS_UNKNOWN, CAT_NAME_TO_DETECT_CODE

logger = logging.getLogger(__name__)


def _normalize_access(val):
    """接入方式归一化为码：'1'/含"经互感" → ACCESS_HUGAN；'0'/含"直接" → ACCESS_DIRECT；其余 UNKNOWN。

    Excel 接入方式列是中文（经互感接入/直接接入），JSON 路径 reader 已推断出码；
    此处统一两条路径的接入方式为同一套码，核心算法只按码判断（8.28 解耦）。
    """
    if val is None or pd.isna(val):
        return ACCESS_UNKNOWN
    s = str(val).strip()
    if s in (ACCESS_HUGAN, '1', '1.0') or '经互感' in s:
        return ACCESS_HUGAN
    if s in (ACCESS_DIRECT, '0', '0.0') or '直接' in s:
        return ACCESS_DIRECT
    return ACCESS_UNKNOWN


def process_data(dfs, sched_cfg):
    """填充 scheduler 模块级全局变量（22 个输入）。

    逻辑与 8.16 脚本相应段落逐行一致。
    dfs 来自 reader（Excel 或 JSON），列名与算法期望一致。
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
    df_non_demand_target = dfs['non_demand_target']

    logger.info("===== 数据准备开始 =====")
    logger.info("输入规模：spec=%d行 整体情况=%d行 仓配置=%d行 线体=%d行 时间配置=%d行 "
                "间隔配置=%d行 合格库存=%d行 非合格库存=%d行 到货=%d行 需求=%d行 非需求目标=%d行",
                len(df_spec), len(df_overall), len(df_chamber_config), len(df_line_info),
                len(df_time_config), len(df_gap_config), len(df_qualified),
                len(df_unqualified), len(df_arrival), len(df_demand),
                len(df_non_demand_target))

    # ---- 大小码映射（设备码(小码) -> 设备类型码大码，从需求明细表）----
    dev_code_to_big_code = {}
    for _, row in df_demand.iterrows():
        small_code = row['设备码'] if pd.notna(row['设备码']) else ''
        big_code = row['设备类型码大码'] if pd.notna(row['设备类型码大码']) else ''
        if small_code and big_code and small_code != big_code:
            dev_code_to_big_code[small_code] = big_code
    logger.info("大小码映射：%d 条", len(dev_code_to_big_code))

    # ---- 非需求设备目标设备类型映射（设备类型码大码 -> [(目标设备类型码, 分配比例%)]）----
    non_demand_target_config = defaultdict(list)
    for _, row in df_non_demand_target.iterrows():
        original_code = str(row['设备类型码大码'])
        target_code = str(row['目标设备类型码'])
        percentage = float(row['分配比例（%）'])
        non_demand_target_config[original_code].append((target_code, percentage))
    logger.info("非需求设备目标类型映射：%d 个原码", len(non_demand_target_config))

    # ---- 需求设备目标设备类型比例映射（大码 -> [(小码, 比例)]，从需求明细表）----
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
    logger.info("需求设备目标类型比例映射：%d 个大码", len(big_code_target_proportions))

    # ---- 低压电流互感器子类型映射（基于设备码描述区分大变比、DBI、普通型）----
    dev_code_to_low_voltage_subtype = {}
    for _, row in df_spec.iterrows():
        code = str(row['设备码'])
        cat = str(row['设备分类']) if pd.notna(row['设备分类']) else ''
        if cat == '低压电流互感器':
            desc = str(row['设备码描述']) if pd.notna(row['设备码描述']) else ''
            subtype = classify_low_voltage_subtype(desc)
            if not desc:
                logger.debug("低压电流互感器设备码 %s 无设备码描述，默认子类型「%s」", code, subtype)
            dev_code_to_low_voltage_subtype[code] = subtype
    logger.info("低压电流互感器子类型映射：%d 个设备码", len(dev_code_to_low_voltage_subtype))

    # ---- 设备码映射（8.16 起以 VW_DETECT_EQUIP_TYPE 码为统一键）----
    dev_code_to_cat = {}        # 设备码 → VW_DETECT_EQUIP_TYPE 编码
    dev_code_to_cat_name = {}   # 设备码 → 设备分类名称（中文）
    dev_code_to_access = {}
    dev_code_to_detect_scheme_id = {}  # 设备码 → detectSchemeId（参数标识，8.17 新增）
    for _, row in df_spec.iterrows():
        code = row['设备码']
        cat = row['设备分类']
        access = _normalize_access(row.get('接入方式'))
        # 低压电流互感器使用子类型分类
        if cat == '低压电流互感器':
            cat = dev_code_to_low_voltage_subtype.get(str(code), cat)
        detect_code = CAT_NAME_TO_DETECT_CODE.get(cat, None)
        dev_code_to_cat[code] = detect_code if detect_code is not None else cat
        dev_code_to_cat_name[code] = cat
        dev_code_to_access[code] = access
        # 读取参数标识作为 detectSchemeId（8.17 新增；用 row.get 兜底旧 Excel 无此列的场景）
        scheme_id = row.get('参数标识')
        if pd.notna(scheme_id):
            dev_code_to_detect_scheme_id[code] = int(scheme_id)
        if not cat:
            logger.debug("设备码 %s 无设备分类，映射为空（若进入排程将报错）", code)
    logger.info("设备码映射：%d 个设备码", len(dev_code_to_cat))
    logger.info("detectSchemeId映射: %d 条设备码映射", len(dev_code_to_detect_scheme_id))

    # ---- 检定仓解析 ----
    df_overall[['线体编号', '线体名称', '检定仓类型', '检定仓编号']] = df_overall[['线体编号', '线体名称', '检定仓类型', '检定仓编号']].ffill()
    df_overall['所检设备表类型'] = df_overall['所检设备表类型'].astype(str).str.replace('\n', ' ', regex=False)

    chambers = {}
    chamber_type_id_map = {}
    n_skip_no_chamber = 0
    n_skip_no_capacity = 0
    n_skip_unclassified = 0
    for _, row in df_overall.iterrows():
        line_id = row['线体编号']
        chamber_id = row['检定仓编号']
        if pd.isna(chamber_id):
            n_skip_no_chamber += 1
            logger.debug("跳过无检定仓编号的整体情况行（线体 %s）", line_id)
            continue
        device_desc = row['所检设备表类型']
        capacity = row['表位数']
        if pd.isna(capacity):
            n_skip_no_capacity += 1
            logger.debug("跳过无表位数的仓行（线体 %s 仓 %s）", line_id, chamber_id)
            continue
        dev_cat = parse_device_category(device_desc)
        if dev_cat is None:
            n_skip_unclassified += 1
            logger.debug("跳过无法识别设备分类的仓行（线体 %s 仓 %s，所检设备表类型「%s」）",
                         line_id, chamber_id, device_desc)
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

    logger.info("检定仓解析：加载 %d 个检定仓，仓类型映射 %d 个"
                "（整体情况跳过 %d 行：无仓编号 %d / 无表位数 %d / 无法识别分类 %d）",
                len(chambers), len(chamber_type_id_map),
                n_skip_no_chamber + n_skip_no_capacity + n_skip_unclassified,
                n_skip_no_chamber, n_skip_no_capacity, n_skip_unclassified)

    # ---- 设备检定时间（8.16 起以 VW_DETECT_EQUIP_TYPE 码为键；含默认值回退）----
    spec_time = {}
    for _, row in df_spec.iterrows():
        cat = row['设备分类']
        if pd.isna(cat):
            # 无分类设备码（0812 的 detectSchList 独有码）带 schTime 会混成垃圾键，
            # 记录并跳过，不让它污染码→时长映射
            if pd.notna(row['自动检定时间']):
                logger.warning("设备码 %s 无设备分类，自动检定时间 %s 无法归属，跳过",
                               row['设备码'], row['自动检定时间'])
            continue
        detect_code = CAT_NAME_TO_DETECT_CODE.get(cat, None)
        if detect_code is not None and pd.notna(row['自动检定时间']):
            spec_time[detect_code] = int(row['自动检定时间'])
    n_default = 0
    for k, v in sched_cfg.default_times.items():
        if k not in spec_time:
            spec_time[k] = v
            n_default += 1
            logger.debug("设备分类码 %s（%s）无自动检定时间，使用默认时长 %d 分钟/批",
                         k, get_detect_equip_type_name(k), v)
    logger.info("检定时间配置：%d 个设备分类码（数据 %d + 默认值回退 %d）",
                len(spec_time), len(spec_time) - n_default, n_default)

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
            if isinstance(work_date, str):
                work_date = datetime.strptime(work_date, '%Y-%m-%d').date()
            elif hasattr(work_date, 'date'):
                work_date = work_date.date()
            time_map[work_date] = (sh, sm, eh, em)
    logger.info("工作日时间配置：%d 天", len(time_map))

    # ---- 最晚完工日期：取排程时间配置的最大工作日日期（动态计算，替代 8.11 写死的 2026-04-30）----
    max_work_date = max(time_map.keys()) if time_map else scheduler.MAX_WORK_DATE
    logger.info("最晚完工日期：%s（依据排程时间配置 %d 天的最大日期）", max_work_date, len(time_map))

    # ---- 调度时间间隔与加班时长（含默认值回退）----
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
            gap_map[line_id] = sched_cfg.default_gap_minutes
            overtime_map[line_id] = 0
    logger.info("调度时间间隔：%d 条线体（分钟），各线体加班时长配置: %s",
                len(gap_map), overtime_map)

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
    initial_inventory = dict(inventory)  # 期初合格品库存快照，用于排程完成后校正"是否为需求优先"标记
    logger.info("初始库存（按设备码）: %s", dict(inventory))

    # ---- 待处理批次（非合格品库存 + 到货计划）----
    pending_batches = deque()
    n_unqualified = 0
    # 【甲方20260825新需求/8.28 调整】解析"是否已抽检"标志与"抽检数量"
    #   是否已抽检=否 的批次，按抽检数量先抽检（到货后抽样检测），该部分只做抽检、
    #   不再安排首检（8.28 起抽检数量从批次数量中扣除）
    # 注：row.get 兜底旧 Excel 无「是否已抽检/抽检数量」列的场景（视为已抽检、抽检数量 0）
    batch_sample_info = {}  # 到货批次号 → {'sampled': 是否已抽检, 'sample_qty': 抽检数量}

    for _, row in df_unqualified.iterrows():
        batch_no = row['到货批次号']
        dev_code = row['设备类型码']
        qty = int(row['可检库存'])
        est_date = datetime(2026, 1, 1, 0, 0, 0)
        sampled = str(row.get('是否已抽检')).strip() == '是' if pd.notna(row.get('是否已抽检')) else True
        sample_qty = int(row.get('抽检数量')) if pd.notna(row.get('抽检数量')) else 0
        if not sampled and sample_qty > 0:
            sample_qty = min(sample_qty, qty)
        batch_sample_info[str(batch_no)] = {'sampled': sampled, 'sample_qty': sample_qty}
        # 未抽检批次的抽检数量从批次数量中扣除，该部分只做抽检、不再安排首检
        first_check_qty = qty if (sampled or sample_qty <= 0) else qty - sample_qty
        pending_batches.append([str(batch_no), dev_code, first_check_qty, qty, est_date])
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
        sampled = str(row.get('是否已抽检')).strip() == '是' if pd.notna(row.get('是否已抽检')) else True
        sample_qty = int(row.get('抽检数量')) if pd.notna(row.get('抽检数量')) else 0
        if not sampled and sample_qty > 0:
            sample_qty = min(sample_qty, qty)
        batch_sample_info[str(batch_no)] = {'sampled': sampled, 'sample_qty': sample_qty}
        # 未抽检批次的抽检数量从批次数量中扣除，该部分只做抽检、不再安排首检
        first_check_qty = qty if (sampled or sample_qty <= 0) else qty - sample_qty
        pending_batches.append([str(batch_no), dev_code, first_check_qty, qty, est_date])

    pending_batches = deque(sorted(pending_batches, key=lambda x: (x[4], x[0])))
    logger.info("待处理批次总数: %d（非合格品库存 %d 批 + 到货计划 %d 批）",
                len(pending_batches), n_unqualified, len(pending_batches) - n_unqualified)
    need_sampling_batches = [bn for bn, info in batch_sample_info.items()
                             if not info['sampled'] and info['sample_qty'] > 0]
    logger.info("需安排抽检的批次: %d 个", len(need_sampling_batches))
    for bn in need_sampling_batches:
        logger.info("  %s: 抽检数量 %d", bn, batch_sample_info[bn]['sample_qty'])

    # ---- 补充映射：从需求明细表的"设备分类"列读取，补充 spec 中缺失的设备码映射 ----
    for _, row in df_demand.iterrows():
        dev_code = row['设备类型码大码']
        dev_cat_from_demand = row['设备分类'] if pd.notna(row['设备分类']) else ''
        if dev_cat_from_demand and dev_code not in dev_code_to_cat:
            # 低压电流互感器也使用子类型映射
            if dev_cat_from_demand == '低压电流互感器':
                dev_cat_from_demand = dev_code_to_low_voltage_subtype.get(str(dev_code), dev_cat_from_demand)
            detect_code = CAT_NAME_TO_DETECT_CODE.get(dev_cat_from_demand, None)
            dev_code_to_cat[dev_code] = detect_code if detect_code is not None else dev_cat_from_demand
            logger.debug("需求设备码 %s：spec 无映射，按需求明细设备分类「%s」补充 → 分类码 %s",
                         dev_code, dev_cat_from_demand, dev_code_to_cat[dev_code])
        elif dev_code_to_cat.get(dev_code) in (None, ''):
            # spec 无该码或分类未识别，且需求明细也未提供可用分类 → 该需求排程将失败
            if dev_cat_from_demand:
                logger.warning("需求设备码 %s 的 spec 分类未识别，需求明细设备分类「%s」未采用，"
                               "该需求排程将失败", dev_code, dev_cat_from_demand)
            else:
                logger.warning("需求设备码 %s 无法建立分类映射（spec 无分类、需求明细也无设备分类），"
                               "该需求排程将失败", dev_code)

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
    scheduler.dev_code_to_cat_name = dev_code_to_cat_name
    scheduler.dev_code_to_access = dev_code_to_access
    scheduler.dev_code_to_detect_scheme_id = dev_code_to_detect_scheme_id
    scheduler.dev_code_to_big_code = dev_code_to_big_code
    scheduler.non_demand_target_config = non_demand_target_config
    scheduler.big_code_target_proportions = big_code_target_proportions
    scheduler.dev_code_to_low_voltage_subtype = dev_code_to_low_voltage_subtype
    scheduler.chambers = chambers
    scheduler.chamber_type_id_map = chamber_type_id_map
    scheduler.spec_time = spec_time
    scheduler.line_name_map = line_name_map
    scheduler.time_map = time_map
    scheduler.MAX_WORK_DATE = max_work_date
    scheduler.gap_map = gap_map
    scheduler.overtime_map = overtime_map
    scheduler.base_date = base_date
    scheduler.inventory = inventory
    scheduler.initial_inventory = initial_inventory
    scheduler.pending_batches = pending_batches
    scheduler.batch_sample_info = batch_sample_info
    scheduler.demand_by_month = demand_by_month
    scheduler.months = months
    # chamber_time / schedule_details 由 run_scheduling() 内部初始化
