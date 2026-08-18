"""
检定模块 — 设备分类解析（8.16 版）
============================
8.16 脚本 `检定排程python代码_8.16（修改映射）.py` 引入统一码值体系：
`parse_device_category` 由返回中文名改为返回 **VW_DETECT_EQUIP_TYPE 编码**（int），
spec / chambers / demand 三处分类身份统一以码为键。

8.16 相对 8.11 的分类变化：
- 三相直接表→2、三相互感表/三相互感电能表→3 **分开**（8.11 折叠为"三相电能表"，
  导致 spec 分类与 chambers 键不匹配、三相设备排程失败）
- 低压电流互感器按描述区分 3 种子类型：大变比(9) / DBI(10) / 普通型(8)
- 全部终端类（集中器/负荷控制/负荷管理/配变监测/智能量测/厂站）→ 14

已记录、待算法负责人确认（勿改）：VW_DETECT_EQUIP_TYPE 编码 12/13/16/17 转出的名称
（负荷**管理**终端 / 配变监测**计量**终端）在此分类器**认不出**（只认 负荷控制终端 /
配变监测终端），对应仓会被静默跳过——见 docs/导出数据/检定数据记录文档.md §2-C。
"""
from __future__ import annotations

from .constants import (
    CAT_NAME_TO_DETECT_CODE,
    CAT_NAME_TO_EQUIP_CLS_CODE,
    DETECT_CODE_TO_NAME,
    EQUIP_CLS_CODE_TO_NAME,
)


def parse_device_category_name(desc):
    """设备描述 -> 设备分类（中文名）。8.16 关键词逻辑原样迁移，仅返回名称。

    供 reader 合成 spec 设备分类用：spec.设备分类 必须是中文名（prepare 再经
    CAT_NAME_TO_DETECT_CODE 转码），不能直接落码。
    """
    if desc is None:
        return None
    desc = str(desc).lower()
    if '单相电能表' in desc:
        return '单相电能表'
    elif '三相直接表' in desc:
        return '三相直接表'
    elif '三相互感表' in desc or '三相互感电能表' in desc:
        return '三相互感表'
    elif '集中器' in desc or '负荷控制终端' in desc or '配变监测终端' in desc \
            or '智能量测终端' in desc or '厂站终端' in desc:
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


def parse_device_category(desc):
    """设备描述 -> VW_DETECT_EQUIP_TYPE 编码（8.16 语义）。

    :param desc: 所检设备表类型名称（编码已先经 VW_DETECT_EQUIP_TYPE 转名）
    :return: 编码 int（单相=1/三相直接表=2/三相互感表=3/电压互感器=4·5/电流互感器=6·7/
             低压CT=8·9·10/终端=14）；无法识别返回 None
    """
    cat = parse_device_category_name(desc)
    if cat is None:
        return None
    return CAT_NAME_TO_DETECT_CODE.get(cat, cat)


def classify_low_voltage_subtype(desc):
    """低压电流互感器按「设备码描述」区分子类型（8.16 脚本 L187-200 内联逻辑一致）。

    优先级：大变比 > DBI > 普通型（与 8.16 一致）。
    """
    if not desc:
        return '低压电流互感器'
    desc = str(desc)
    if '大变比' in desc:
        return '低压电流互感器_大变比'
    elif 'dbi' in desc.lower():
        return '低压电流互感器_DBI'
    else:
        return '低压电流互感器'


# ==================================================================
# 码值推导 helper（8.16 脚本迁移；输出行的编码/名称字段用）
# ==================================================================

def get_detect_equip_type_name(code):
    """VW_DETECT_EQUIP_TYPE 编码 -> 名称；未知码返回原值字符串。"""
    return DETECT_CODE_TO_NAME.get(code, str(code))


def get_equip_cls_code(cat_name):
    """设备分类名称 -> VW_EQUIP_CLS 编码。"""
    return CAT_NAME_TO_EQUIP_CLS_CODE.get(cat_name, None)


def get_equip_cls_name(code):
    """VW_EQUIP_CLS 编码 -> 名称；未知码返回原值字符串。"""
    return EQUIP_CLS_CODE_TO_NAME.get(code, str(code))


def get_equip_categ_code(cat_name):
    """设备分类名称 -> VW_EQUIP_CATEG 设备类别编码（8.16 L77-85 原文）。

    电能表（含直接表/互感表）→ 1；互感器 → 2；计量自动化终端 → 9；否则 None。
    """
    if any(k in cat_name for k in ['电能表', '直接表', '互感表']):
        return 1  # 电能表
    if any(k in cat_name for k in ['电压互感器', '电流互感器', '低压电流互感器']):
        return 2  # 互感器
    if any(k in cat_name for k in ['终端', '集中器', '负荷']):
        return 9  # 计量自动化终端
    return None
