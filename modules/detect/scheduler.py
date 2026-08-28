"""
检定排程 — 核心调度算法（8.28 版）
===================================
从 8.28 脚本 `docs/算法脚本/检定排程/检定排程python代码_8.28最新.py` 迁移，
**核心逻辑零修改**（仅补充日志 + 输出码值化改造，不改变任何计算）。

8.28 变化（相对 8.25，本文件体现）：
- 抽检重构：ensure_sample_inspection()（batch_sample_done 缓存、无抽检返回 0），
  schedule_batch 参数化（detect_type_code / count_to_inventory），抽检走同一排程函数
  （内部批次号 S 段、检定类型=2、不入库存、按占比最大的需求目标设备类型码）
- 未抽检批次的抽检数量从批次数量中扣除（该部分只做抽检、不再安排首检）
- 12.7 需求优先事后校正：首检记录按各设备码总需求扣除期初库存（initial_inventory）后的
  需检定数量，按完成时间先后标记 是/否；抽检记录不参与
- schedule_details 的 是否为需求优先 由 1/0 改 是/否（内部）；get_batch_last_p_end_minutes
  相应比较 '是'
- get_next_start_minutes 的 earliest 分支简化为 candidate_min = earliest_start_minutes
- 输出聚合：schedule_summary / batch_alloc 键含 检定类型编码/名称（8.25 起）；输出码值化：
  需求优先 是/否 → '1'/'0'，VW 编码列 → 2 位字符串，中文名称列删除（Excel 与 JSON 同步）

8.25 变化（相对 8.17，本文件体现；甲方 20260825 新需求 + 接口 v0.0.6）：
- 抽检流程：未抽检批次（是否已抽检=否 且 抽检数量>0）先安排抽检（检定类型=2 到货后抽样检测），
  抽检完成后才做首检；抽检不产生合格品库存
- 出参新增 detectType（检定类型编码：02 抽样试验 / 03 首次检定）

8.17 变化（相对 8.16，本文件体现）：
- 新增 dev_code_to_detect_scheme_id 映射（设备码 → detectSchemeId，来源 spec.参数标识）
  与 get_detect_scheme_id()（自动尝试大小码匹配）
- 输出行新增 detectSchemeId（规格表参数标识；查不到返回空串）

8.16 码值适配（相对 8.11，本文件体现）：
- 分类统一以 VW_DETECT_EQUIP_TYPE 码为键：dev_code_to_cat 存码、新增 dev_code_to_cat_name
  存中文名；chambers.capacity / spec_time 均以码为键
- get_priority 按码比较（14 终端 / 2·3 三相 / 1 单相）；终端仓（仓类型ID=5）过滤、单相排序
  均按码判断
- 输出行新增码值字段（检定设备类型编码/名称、设备分类/类别编码与名称、检定仓类型编码、
  需求计划类型/检定类型编码与名称），是否为需求优先 由 是/否 改 1/0

8.11 相对 8.03 的变化（本文件体现）：
- 支持加班：get_next_start_minutes 允许在正常下班后继续排程（overtime_map）
- 大小码映射（dev_code_to_big_code）与需求设备目标比例映射（big_code_target_proportions）
- 非需求设备按目标设备类型配置拆分（schedule_non_demand_batch）
- 低压电流互感器子类型（dev_code_to_low_voltage_subtype）
- 仓排序策略分优先级/单相/非需求三档
- 需求尾仓向上取整（减少空仓）；批次内 N 不早于同批次 P 的最晚完成时间
- 需求批次的"目标设备类型码"按需求明细小码比例分配

日志约定：
- INFO    : 月份/设备级调度流程、批次安排决策、主调度起止
- WARNING : 计算问题——批次耗尽仍欠缺口、批次无分类/无对应仓被跳过、未生成任何子任务
- DEBUG   : 每个检定子任务的分配明细（仓、数量、起止时间）、可用仓数、终端仓过滤明细

模块级全局变量由 prepare.process_data() 在执行前填充（22 个输入 + 2 个输出）：
    dev_code_to_cat / dev_code_to_cat_name / dev_code_to_access / dev_code_to_big_code /
    dev_code_to_detect_scheme_id / batch_sample_info / initial_inventory /
    non_demand_target_config / big_code_target_proportions /
    dev_code_to_low_voltage_subtype / chambers / chamber_type_id_map /
    spec_time / line_name_map / time_map / gap_map / overtime_map / base_date /
    inventory / pending_batches / demand_by_month / months
    chamber_time / schedule_details / batch_sample_done（由 run_scheduling() 内部填充/重置）

其余已知阻断项（见 docs/导出数据/检定数据记录文档.md）：
- schTime 污染 / 分类关键词 12·13·16·17 认不出 / arriveBatchList.detectEquipType 全空 —— 待算法负责人确认，不擅修
"""
import logging
import math
from collections import defaultdict, deque
from datetime import date, datetime, timedelta

import pandas as pd

from .category import (
    get_detect_equip_type_name,
    get_equip_categ_code,
    get_equip_cls_code,
    get_equip_cls_name,
)
from .constants import (
    ACCESS_HUGAN,
    CAT_NAME_TO_DETECT_CODE,
    DEFAULT_DETECT_TYPE_CODE,
    DEFAULT_DMD_PLAN_TYPE_CODE,
    DETECT_TYPE_CODE_TO_NAME,
    DMD_PLAN_TYPE_CODE_TO_NAME,
    EQUIP_CATEG_CODE_TO_NAME,
    SAMPLE_DETECT_TYPE_CODE,
)

logger = logging.getLogger(__name__)

# ==================================================================
# 模块级共享变量（由 prepare.process_data() 填充）
# ==================================================================

dev_code_to_cat = {}
dev_code_to_cat_name = {}  # 设备码 → 设备分类名称（中文），输出名称用
dev_code_to_access = {}
dev_code_to_detect_scheme_id = {}  # 设备码 → detectSchemeId（参数标识，8.17 新增）
dev_code_to_big_code = {}
non_demand_target_config = defaultdict(list)
big_code_target_proportions = {}
dev_code_to_low_voltage_subtype = {}
chambers = {}
chamber_type_id_map = {}
spec_time = {}
line_name_map = {}
time_map = {}
gap_map = {}
overtime_map = {}
base_date = None
inventory = None            # defaultdict(int)
initial_inventory = {}      # 期初合格品库存快照（12.7 需求优先校正用，8.28）
pending_batches = None      # deque()
demand_by_month = None      # defaultdict(list)
months = []
batch_sample_info = {}      # 到货批次号 → {'sampled': 是否已抽检, 'sample_qty': 抽检数量}（8.28）

chamber_time = {}
schedule_details = []
batch_sample_done = {}      # 批次号 → 抽检完成时间(分钟)；值为0表示无需抽检（8.28）

MAX_DAY_SEARCH = 365 * 10  # 最大搜索天数，防止死循环
# 最晚完工日期：排程时间配置中最后一天。
# 默认不设上限；prepare.process_data() 会依据排程时间配置（time_config）的最大工作日日期覆盖，
# 因此排程只会在配置声明的日期范围内进行（替代 8.11 写死的 2026-04-30）。
MAX_WORK_DATE = date.max


# ==================================================================
# 核心函数（8.16 原样迁移，零修改）
# ==================================================================

def get_priority(dev_code):
    """设备类型优先级（8.16 起按 VW_DETECT_EQUIP_TYPE 码判断）。

    14 智能量测终端 > 2/3 三相 > 1 单相 > 其他。
    """
    cat = dev_code_to_cat.get(dev_code, 0)
    if cat == 14:  # 智能量测终端
        return 0
    elif cat == 2 or cat == 3:  # 三相电能表（三相直接表/三相互感表）
        return 1
    elif cat == 1:  # 单相电能表
        return 2
    else:
        return 3


def get_detect_scheme_id(dev_code):
    """根据设备码获取 detectSchemeId（参数标识），自动尝试大小码匹配（8.17 新增）。"""
    if dev_code in dev_code_to_detect_scheme_id:
        return dev_code_to_detect_scheme_id[dev_code]
    big_code = dev_code_to_big_code.get(dev_code, dev_code)
    if big_code in dev_code_to_detect_scheme_id:
        return dev_code_to_detect_scheme_id[big_code]
    return None


def is_workday(day):
    """仅认排程时间配置中明确定义的工作日，不自动补全周末以外的工作日。"""
    if day > MAX_WORK_DATE:
        return False
    return day in time_map


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
    """计算下一个子任务的开始时间（绝对分钟）。支持加班：
    允许在正常下班时间后继续排程，但不超过加班时长上限。"""
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
            # 8.28：直接从最早开始时间重新校验，由其落入的工作时段/次日逻辑保证不早于 earliest_start
            candidate_min = earliest_start_minutes
            continue

        return int((start_abs - base_date).total_seconds() / 60)

    raise OverflowError(f"时间计算超过 {MAX_DAY_SEARCH} 天仍未找到合适时段，请检查排程配置。")


def ensure_sample_inspection(batch_no, dev_code, month, earliest_start=0, target_splits=None):
    """批次是否已抽检标志为'否'时，按抽检数量先安排抽检（检定成需求的设备类型码）；
    target_splits: [(排程设备码, 目标设备类型码, 比例)]，取占比最大的需求目标设备类型码；
    返回抽检完成时间（分钟，作为该批次后续首检的最早开始时间），无需抽检时返回0"""
    if batch_no in batch_sample_done:
        return batch_sample_done[batch_no]
    info = batch_sample_info.get(batch_no)
    if info is None or info['sampled'] or info['sample_qty'] <= 0:
        batch_sample_done[batch_no] = 0
        return 0
    # 抽检数量一次性排程（按占比最大的需求目标设备类型码），
    # 由 schedule_batch 按仓容量装满一仓再分下一仓，避免上一仓未装满又多分一仓
    if target_splits:
        s_dev, t_dev, _ = max(target_splits, key=lambda t: t[2])
    else:
        s_dev, t_dev = dev_code, dev_code
    logger.info("  批次 %s 未抽检，先安排抽检 %d 台（排程设备码 %s → 目标设备类型码 %s）",
                batch_no, info['sample_qty'], s_dev, t_dev)
    before = len(schedule_details)
    schedule_batch(batch_no, s_dev, info['sample_qty'], is_priority=False, month=month,
                   earliest_start=earliest_start, target_dev_code=t_dev,
                   detect_type_code=SAMPLE_DETECT_TYPE_CODE, count_to_inventory=False)
    sample_end = 0
    for item in schedule_details[before:]:
        end_min = int((item['预计完成时间'] - base_date).total_seconds() / 60)
        if end_min > sample_end:
            sample_end = end_min
    batch_sample_done[batch_no] = sample_end
    return sample_end


def schedule_batch(batch_no, dev_code, quantity, is_priority, month, earliest_start=0, target_dev_code=None,
                   detect_type_code=DEFAULT_DETECT_TYPE_CODE, count_to_inventory=True):
    """把一批设备安排到检定仓，生成一个或多个子任务。

    8.28 起支持抽检子任务（detect_type_code=2）与库存不入账（count_to_inventory=False）。
    """
    if quantity <= 0:
        return 0
    dev_cat = dev_code_to_cat.get(dev_code)
    if dev_cat is None:
        raise ValueError(f"设备码 {dev_code} 无法映射到设备分类")
    # 若未指定目标设备类型码，则默认使用设备码本身
    if target_dev_code is None:
        target_dev_code = dev_code
    logger.info("  安排批次 %s | 设备码 %s | 数量 %d | 需求优先=%s | 月份=%s | 目标设备类型码=%s",
                batch_no, dev_code, quantity, is_priority, month, target_dev_code)
    available = []
    for ch, info in chambers.items():
        cap = info['capacity'].get(dev_cat)
        if cap and cap > 0:
            # 终端仓（仓类型ID=5）只允许经互感接入的终端（智能量测终端=编码14）
            # 8.28 起接入方式按码判断（ACCESS_HUGAN='1'），Excel 中文已在数据层归一化
            if dev_cat == 14 and chamber_type_id_map.get(ch, 0) == 5:
                access = dev_code_to_access.get(dev_code, '')
                if access != ACCESS_HUGAN:
                    logger.debug("    批次 %s 设备码 %s 接入方式码「%s」非经互感，跳过终端仓 %s",
                                 batch_no, dev_code, access or '空', ch)
                    continue
            available.append((ch, cap))
    if not available:
        raise ValueError(f"没有支持设备类型 {get_detect_equip_type_name(dev_cat)} 的检定仓！")
    logger.debug("    批次 %s 可用检定仓 %d 个", batch_no, len(available))

    # 排序策略：
    # - 单相电能表 + 需求优先：所有仓都可用，优先使用兼容仓（dev_count > 1），专用仓也参与排程
    # - 其他设备 + 需求优先：专用仓优先（dev_count小）
    # - 非需求优先：所有仓都可用，优先使用兼容仓（dev_count > 1）吸收富余产能
    if is_priority and dev_cat == 1:
        available.sort(key=lambda x: (chamber_time[x[0]], -chambers[x[0]]['dev_count'], -x[0][0]))
    elif is_priority:
        available.sort(key=lambda x: (chamber_time[x[0]], chambers[x[0]]['dev_count'], -x[0][0]))
    else:
        available.sort(key=lambda x: (chamber_time[x[0]], -chambers[x[0]]['dev_count'], -x[0][0]))

    remaining = quantity
    sub_counter = 1

    # 出参码值（equipCls / equipCateg 按 VW_DETECT_EQUIP_TYPE 码推导）+ detectSchemeId，循环前算一次
    # 8.28 起核心按码推导，不再走中文名中转（码→码映射见 constants.DEV_CAT_TO_*）
    equip_cls_code = get_equip_cls_code(dev_cat)
    equip_categ_code = get_equip_categ_code(dev_cat)
    detect_scheme_id = get_detect_scheme_id(dev_code)  # 8.17：规格表参数标识

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
            logger.warning("设备码 %s 批次 %s 剩余 %d 无法在 %s 前排程，跳过",
                           dev_code, batch_no, remaining, MAX_WORK_DATE)
            remaining = 0
            break
        end_min = start_min + duration
        start_time = base_date + timedelta(minutes=start_min)
        end_time = base_date + timedelta(minutes=end_min)
        if detect_type_code == SAMPLE_DETECT_TYPE_CODE:
            priority_label = 'S'
        else:
            priority_label = 'P' if is_priority else 'N'
        internal_batch = f"{month}-{batch_no}-{priority_label}-{sub_counter}"
        logger.debug("    子任务 %s：仓 %s 分配 %d 台，%s → %s",
                     internal_batch, ch, batch_qty,
                     start_time.strftime('%Y-%m-%d %H:%M:%S'),
                     end_time.strftime('%Y-%m-%d %H:%M:%S'))
        chamber_type_name = chambers[ch]['type_name']
        schedule_details.append({
            '月份': month,
            '检定线ID': ch[0],
            '检定线名称': line_name_map.get(ch[0], ''),
            '检定仓编号': ch[1],
            '检定仓类型': chamber_type_name,
            '检定仓类型编码': chamber_type_id_map.get(ch),
            '检定仓类型名称': chamber_type_name,
            '检定设备类型编码': dev_cat,
            '检定设备类型名称': get_detect_equip_type_name(dev_cat),
            '设备类型': get_detect_equip_type_name(dev_cat),
            '设备分类编码': equip_cls_code,
            '设备分类名称': get_equip_cls_name(equip_cls_code) if equip_cls_code else '',
            '设备类别编码': equip_categ_code,
            '设备类别名称': EQUIP_CATEG_CODE_TO_NAME.get(equip_categ_code, '') if equip_categ_code else '',
            '设备码': dev_code,
            '目标设备类型码': target_dev_code,
            '到货批次号': batch_no,
            '是否为需求优先': '是' if is_priority else '否',
            '需求计划类型编码': DEFAULT_DMD_PLAN_TYPE_CODE,
            '需求计划类型名称': DMD_PLAN_TYPE_CODE_TO_NAME.get(DEFAULT_DMD_PLAN_TYPE_CODE, ''),
            '检定类型编码': detect_type_code,
            '检定类型名称': DETECT_TYPE_CODE_TO_NAME.get(detect_type_code, ''),
            'detectSchemeId': detect_scheme_id if detect_scheme_id is not None else '',
            '内部批次号': internal_batch,
            '每批数量': batch_qty,
            '预计开始时间': start_time,
            '预计完成时间': end_time,
            '检定时长(天)': round(duration / 1440, 1),
            '检定时长(分钟/批)': duration
        })
        chamber_time[ch] = end_min
        if count_to_inventory:
            inventory[dev_code] += batch_qty
        remaining -= batch_qty
        available[0] = (ch, max_cap)
        sub_counter += 1
    return quantity


def get_max_chamber_cap(dev_code):
    """获取某设备类型的最大仓容量。"""
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
    """获取某批次在 schedule_details 中所有 P 子任务的最晚完成时间（绝对分钟）。"""
    max_end = 0
    for item in schedule_details:
        if item['到货批次号'] == batch_no and item['是否为需求优先'] == '是':
            end_min = int((item['预计完成时间'] - base_date).total_seconds() / 60)
            if end_min > max_end:
                max_end = end_min
    return max_end


def schedule_non_demand_batch(batch_no, dev_code, quantity, month, earliest_start):
    """按非需求设备目标设备类型配置，将非需求批次按比例拆分并排程。"""
    targets = non_demand_target_config.get(dev_code, [(dev_code, 100)])
    dev_cat = dev_code_to_cat.get(dev_code, 0)
    # 对于单相电能表(编码1)的非需求批次：设备码应为大码，目标设备类型码应为需求明细中的设备码(小码)
    if dev_cat == 1:
        big_code = dev_code_to_big_code.get(dev_code, dev_code)
        if big_code != dev_code:
            small_code = dev_code
        else:
            targets_list = big_code_target_proportions.get(dev_code, [(dev_code, 1.0)])
            small_code = targets_list[0][0]
        sample_splits = [(big_code, small_code, 1.0)]
    else:
        big_code = dev_code
        small_code = dev_code
        sample_splits = [(t_code, t_code, pct) for t_code, pct in targets]
    sample_end = ensure_sample_inspection(batch_no, dev_code, month, earliest_start, target_splits=sample_splits)
    if sample_end > earliest_start:
        earliest_start = sample_end
    # 若配置中只有一个目标且为100%，直接使用原设备码
    if len(targets) == 1 and targets[0][1] == 100 and targets[0][0] == dev_code:
        if dev_cat == 1:
            return schedule_batch(batch_no, big_code, quantity, is_priority=False, month=month, earliest_start=earliest_start, target_dev_code=small_code)
        else:
            return schedule_batch(batch_no, dev_code, quantity, is_priority=False, month=month, earliest_start=earliest_start, target_dev_code=dev_code)
    total_pct = sum(pct for _, pct in targets)
    scheduled = 0
    # 按比例分配（最后一个目标补齐取整差额）
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


# ==================================================================
# 封装入口（主循环 / 输出构建，8.16 原样迁移）
# ==================================================================

def run_scheduling():
    """主调度循环（8.16 第 547-860 行内联主循环）。填充 chamber_time 与 schedule_details。

    8.16 会在循环内对 pending_batches 整体重新赋值（sorted），
    故须声明为 global（8.03 只做原地修改无需）。
    """
    global chamber_time, schedule_details, pending_batches
    global batch_sample_done
    chamber_time = {ch: 0 for ch in chambers.keys()}
    schedule_details = []
    # 8.28 抽检状态重置（HTTP 长驻服务重入安全：8.28 脚本单次运行无此需要，
    # 这里与 chamber_time/schedule_details 一同重置，单次运行语义与 8.28 完全一致）
    batch_sample_done = {}

    logger.info("===== 主调度开始 =====")
    logger.info("月份列表：%s（共 %d 个月）", months, len(months))

    for month in months:
        # 当月需求汇总（按设备码）
        demand_dict = defaultdict(int)
        for dev_code, qty in demand_by_month[month]:
            demand_dict[dev_code] += qty
        logger.info("月份 %s：当月需求 %d 台（%d 个设备码）",
                    month, sum(demand_dict.values()), len(demand_dict))

        # 同优先级内，20kV 设备优先排程（确保在共用仓中先于 10kV 设备排程）
        # 8.28 起按码判断：20kV 电压/电流互感器码 5/7 先于 10kV 码 4/6
        sorted_dev_codes = sorted(demand_dict.keys(), key=lambda x: (get_priority(x), dev_code_to_cat.get(x) not in (5, 7)))

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

            pending_batches = deque(sorted(pending_batches, key=lambda x: (x[4], x[0])))
            while deficit > 0 and pending_batches:
                # 大小码匹配：如果批次的设备码是小码，尝试匹配大码需求
                found_idx = None
                for i, (b, d, r, _, dt) in enumerate(pending_batches):
                    batch_dev = d
                    mapped_dev = dev_code_to_big_code.get(batch_dev, batch_dev)
                    if batch_dev == dev_code or mapped_dev == dev_code:
                        found_idx = i
                        break
                if found_idx is None:
                    logger.warning("月份 %s 设备码 %s 短缺 %d，但无对应到货批次，跳过",
                                   month, dev_code, deficit)
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

                logger.info("    使用批次 %s（剩余 %d）：需求取 %d 台 + 备货取 %d 台",
                            batch_no, remain, demand_take, stock_take)

                if demand_take > 0:
                    est_minutes = int((est_date - base_date).total_seconds() / 60) if pd.notna(est_date) else 0
                    # 按需求明细中的设备码(小码)比例分配目标设备类型码
                    target_props = big_code_target_proportions.get(dev_code, [(dev_code, 1.0)])
                    sample_splits = [(dev_code, t_code, pct) for t_code, pct in target_props]
                    sample_end = ensure_sample_inspection(batch_no, dev_code, month, est_minutes, target_splits=sample_splits)
                    if sample_end > est_minutes:
                        est_minutes = sample_end
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

            # while 循环在 pending_batches 耗尽时无声退出（8.16 原样），此处显式记录缺口
            if deficit > 0:
                logger.warning("月份 %s 设备码 %s 缺口 %d 台未满足：可用到货批次已耗尽",
                               month, dev_code, deficit)

            # 修正库存：库存 = 生产量 - 已满足的需求量（deficit_original = need - avail）
            original_deficit = need - avail
            inventory[dev_code] = max(0, inventory[dev_code] - original_deficit)

        # 12.5. 处理剩余批次：仅将未来月份无需求的批次排入当前月份
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
                logger.warning("批次 %s 设备码 %s 无对应设备分类，跳过", batch_no, dev_code)
                continue
            support = False
            for info in chambers.values():
                if dev_cat in info['capacity']:
                    support = True
                    break
            if not support:
                logger.warning("批次 %s 类型 %s 无对应检定仓，跳过", batch_no, get_detect_equip_type_name(dev_cat))
                continue

            future_need = future_demand.get(dev_code, 0)
            if future_need >= remain:
                # 全部留待未来月份的需求排程
                new_pending.append(batch)
            elif future_need > 0:
                # 部分需留待未来：将超出部分排入当前月份（非需求优先），剩余留待后续
                excess = remain - future_need
                est_minutes = int((est_date - base_date).total_seconds() / 60) if pd.notna(est_date) else 0
                # 确保非需求优先(N)的 earliest_start 不早于同批次需求优先(P)的最晚完成时间
                batch_p_end = get_batch_last_p_end_minutes(batch_no)
                if batch_p_end > est_minutes:
                    est_minutes = batch_p_end
                schedule_non_demand_batch(batch_no, dev_code, excess, month, earliest_start=est_minutes)
                batch[2] = future_need
                new_pending.append(batch)
            else:
                # 未来无需求，全部排入当前月份（非需求优先）
                est_minutes = int((est_date - base_date).total_seconds() / 60) if pd.notna(est_date) else 0
                batch_p_end = get_batch_last_p_end_minutes(batch_no)
                if batch_p_end > est_minutes:
                    est_minutes = batch_p_end
                schedule_non_demand_batch(batch_no, dev_code, remain, month, earliest_start=est_minutes)

        pending_batches = deque(sorted(new_pending, key=lambda x: (x[4], x[0])))
        logger.info("  月份 %s 处理完成，待处理批次剩余 %d 批", month, len(pending_batches))

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
                logger.warning("批次 %s 设备码 %s 无对应设备分类，跳过", batch_no, dev_code)
                pending_batches.popleft()
                continue
            support = False
            for info in chambers.values():
                if dev_cat in info['capacity']:
                    support = True
                    break
            if not support:
                logger.warning("批次 %s 类型 %s 无对应检定仓，跳过", batch_no, get_detect_equip_type_name(dev_cat))
                pending_batches.popleft()
                continue
            est_minutes = int((est_date - base_date).total_seconds() / 60) if pd.notna(est_date) else 0
            batch_p_end = get_batch_last_p_end_minutes(batch_no)
            if batch_p_end > est_minutes:
                est_minutes = batch_p_end
            schedule_non_demand_batch(batch_no, dev_code, remain, last_month, earliest_start=est_minutes)
            pending_batches.popleft()

    # 12.7. "是否为需求优先"标记校正：
    # 优先满足需求量的部分（总需求扣除期初合格品库存后仍需检定的数量）标为需求优先，
    # 需求数量满足后再检定的部分标为非需求优先；抽检记录不参与，始终为非需求优先
    total_demand_by_dev = defaultdict(int)
    for m, items in demand_by_month.items():
        for dev_code, qty in items:
            total_demand_by_dev[dev_code] += qty

    first_check_groups = defaultdict(list)  # 归一化设备码（小码归并到大码） → [(预计完成时间, 记录序号)]
    for idx, rec in enumerate(schedule_details):
        if rec['检定类型编码'] != DEFAULT_DETECT_TYPE_CODE:
            continue
        norm_dev = dev_code_to_big_code.get(str(rec['设备码']), str(rec['设备码']))
        first_check_groups[norm_dev].append((rec['预计完成时间'], idx))

    for dev, recs in first_check_groups.items():
        need_qty = max(0, total_demand_by_dev.get(dev, 0) - initial_inventory.get(dev, 0))
        recs.sort(key=lambda x: (x[0], x[1]))
        for _, idx in recs:
            if need_qty > 0:
                schedule_details[idx]['是否为需求优先'] = '是'
                need_qty -= schedule_details[idx]['每批数量']
            else:
                schedule_details[idx]['是否为需求优先'] = '否'

    logger.info("是否为需求优先标记校正完成：按各设备码总需求扣除期初库存后的需检定数量，按完成时间先后标记")

    logger.info("===== 主调度结束 =====")
    logger.info("共生成 %d 个子任务，总计 %d 台，剩余未处理批次 %d 批",
                len(schedule_details),
                sum(d['每批数量'] for d in schedule_details),
                len(pending_batches))
    if not schedule_details:
        logger.warning("未生成任何检定子任务，请检查输入数据（设备分类映射 / 检定仓配置 / 到货批次）")


def build_output_dataframes(df_arrival, df_unqualified):
    """构建输出 DataFrame（8.16 第 862-962 行），返回 key 与 output_sheet_names 对齐的字典。

    参数 df_arrival / df_unqualified 是 prepare.process_data 清洗后的原始输入 DataFrame，
    仅用于「原始到货批次」 sheet 的构建。

    8.16 差异：检定仓类型编码采用 chamber_type_id_map（仓类型ID 即 VW_DEVICE_TYPE 码，
    Excel 与 JSON 两条路径都有且一致），而非 8.16 的「仓类型名称→码」反查
    （仓类型名称有三套口径，反查必失败）。
    """
    df_details = pd.DataFrame(schedule_details)
    if df_details.empty:
        # 无排程明细时构造带标准列名的空表，避免下游 groupby 报 KeyError
        df_details = pd.DataFrame(columns=[
            '月份', '检定线ID', '检定线名称', '检定仓编号', '检定仓类型',
            '检定仓类型编码', '检定仓类型名称', '检定设备类型编码', '检定设备类型名称',
            '设备类型', '设备分类编码', '设备分类名称', '设备类别编码', '设备类别名称',
            '设备码', '目标设备类型码', '到货批次号', '是否为需求优先',
            '需求计划类型编码', '需求计划类型名称', '检定类型编码', '检定类型名称',
            'detectSchemeId',
            '内部批次号', '每批数量', '预计开始时间', '预计完成时间',
            '检定时长(天)', '检定时长(分钟/批)',
        ])

    # 将包含设备码的列转换为字符串，避免科学计数法（8.16 在聚合前统一转换）
    def _to_text(x):
        if pd.isna(x):
            return ''
        if isinstance(x, float) and x.is_integer():
            return str(int(x))
        return str(x)

    def convert_dev_code_to_str(df):
        # 设备码/目标设备类型码/detectSchemeId 按文本输出，类别编码列保持数字编码（8.28）
        for col in ['设备码', '目标设备类型码', 'detectSchemeId']:
            if col in df.columns:
                df[col] = df[col].apply(_to_text)
        return df

    df_details = convert_dev_code_to_str(df_details)
    # 需求优先 是/否 → '1'/'0'（在聚合前转换，输出各 sheet 均为编码字符）
    df_details['是否为需求优先'] = df_details['是否为需求优先'].map({'是': '1', '否': '0'}).fillna('0')

    # 检定排程明细（汇总）
    df_schedule_summary = df_details.groupby(
        ['月份', '检定线ID', '检定线名称', '检定设备类型编码', '检定设备类型名称',
         '设备码', '到货批次号', '是否为需求优先', '检定类型编码', '检定类型名称']
    ).agg(
        总检定数量=('每批数量', 'sum'),
        批次数=('内部批次号', 'nunique')
    ).reset_index()

    # 检定时间明细（排序）
    df_details_sorted = df_details.sort_values(['预计开始时间', '检定线ID'])

    # 仓利用率统计
    df_util = df_details.groupby(
        ['月份', '检定线ID', '检定线名称', '检定仓编号', '检定仓类型', '检定仓类型编码']
    ).agg(
        总批次数=('内部批次号', 'nunique'),
        总检定量=('每批数量', 'sum')
    ).reset_index()

    # 到货批次分配明细
    df_batch_alloc = df_details.groupby(
        ['月份', '到货批次号', '检定设备类型编码', '检定设备类型名称', '设备码', '是否为需求优先', '检定类型编码', '检定类型名称']
    ).agg(
        分配数量=('每批数量', 'sum')
    ).reset_index()
    df_batch_alloc['检定时长(分钟/批)'] = df_batch_alloc['检定设备类型编码'].map(spec_time)

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
    # 同一批次号可能对应多行（到货表内重复批次号），8.28 原文 set + drop_duplicates
    # 依赖集合哈希顺序（跨进程不确定）；此处先排序再去重，确定性保留设备码最小的一行
    df_original = (pd.DataFrame(original_arrivals)
                   .sort_values(by=['到货批次号', '设备码'])
                   .drop_duplicates(subset=['到货批次号']))

    # 月度需求汇总
    demand_summary = []
    for month, demands in demand_by_month.items():
        for dev_code, qty in demands:
            dev_cat = dev_code_to_cat.get(dev_code, 0)
            # 8.28 起按码推导（码→码映射），不再走中文名中转
            equip_cls_code = get_equip_cls_code(dev_cat)
            equip_categ_code = get_equip_categ_code(dev_cat)
            demand_summary.append({
                '月份': month,
                '设备码': dev_code,
                '检定设备类型编码': dev_cat,
                '检定设备类型名称': get_detect_equip_type_name(dev_cat),
                '设备分类编码': equip_cls_code,
                '设备分类名称': get_equip_cls_name(equip_cls_code) if equip_cls_code else '',
                '设备类别编码': equip_categ_code,
                '设备类别名称': EQUIP_CATEG_CODE_TO_NAME.get(equip_categ_code, '') if equip_categ_code else '',
                '需求数量': qty,
                '需求计划类型编码': DEFAULT_DMD_PLAN_TYPE_CODE,
                '需求计划类型名称': DMD_PLAN_TYPE_CODE_TO_NAME.get(DEFAULT_DMD_PLAN_TYPE_CODE, ''),
            })
    df_demand_summary = pd.DataFrame(demand_summary)

    # 检定仓配置
    chamber_config_rows = []
    for (line_id, chamber_id), info in chambers.items():
        line_name = line_name_map.get(line_id, '')
        max_cap = max(info['capacity'].values()) if info['capacity'] else 0
        type_name = info['type_name']
        chamber_config_rows.append({
            '检定线ID': line_id,
            '检定线名称': line_name,
            '检定仓编号': chamber_id,
            '仓类型': type_name,
            '检定仓类型编码': chamber_type_id_map.get((line_id, chamber_id)),
            '检定仓类型名称': type_name,
            '每仓最大容量': max_cap
        })
    df_chamber_config_output = pd.DataFrame(chamber_config_rows)

    df_schedule_summary = convert_dev_code_to_str(df_schedule_summary)
    df_details_sorted = convert_dev_code_to_str(df_details_sorted)
    df_batch_alloc = convert_dev_code_to_str(df_batch_alloc)
    df_original = convert_dev_code_to_str(df_original)
    df_demand_summary = convert_dev_code_to_str(df_demand_summary)
    df_util = convert_dev_code_to_str(df_util)
    df_chamber_config_output = convert_dev_code_to_str(df_chamber_config_output)

    # ============ 输出码值化（用户要求：有码值映射的中文一律输出编码字符，Excel 与 JSON 同步）============
    # VW 码值列 → 2 位零填充字符串；中文名称列删除；无码值映射的字段（线体名称/月份/批次号等）保持原样
    _CODE_COLS = ['检定设备类型编码', '设备分类编码', '设备类别编码',
                  '检定类型编码', '需求计划类型编码', '检定仓类型编码']
    _NAME_COLS = ['检定设备类型名称', '设备分类名称', '设备类别名称', '检定类型名称',
                  '需求计划类型名称', '检定仓类型名称', '设备类型', '仓类型', '检定仓类型']

    def _fmt_vw_code(x):
        """VW 码值 → 2 位零填充字符串（3→'03'、14→'14'）；空值 → ''。"""
        if x is None or x == '' or (isinstance(x, float) and pd.isna(x)):
            return ''
        try:
            return f"{int(x):02d}"
        except (ValueError, TypeError):
            return str(x)

    def _format_output(df):
        """输出码值化：编码列转 2 位字符串、删除中文名称列（需求优先已在聚合前转为 '1'/'0'）。"""
        for col in _CODE_COLS:
            if col in df.columns:
                df[col] = df[col].apply(_fmt_vw_code)
        for col in _NAME_COLS:
            if col in df.columns:
                df = df.drop(columns=[col])
        return df

    df_schedule_summary = _format_output(df_schedule_summary)
    df_details_sorted = _format_output(df_details_sorted)
    df_util = _format_output(df_util)
    df_batch_alloc = _format_output(df_batch_alloc)
    df_original = _format_output(df_original)
    df_demand_summary = _format_output(df_demand_summary)
    df_chamber_config_output = _format_output(df_chamber_config_output)

    return {
        'schedule_summary': df_schedule_summary,
        'details_sorted': df_details_sorted,
        'util': df_util,
        'batch_alloc': df_batch_alloc,
        'original': df_original,
        'demand_summary': df_demand_summary,
        'chamber_config': df_chamber_config_output,
    }
