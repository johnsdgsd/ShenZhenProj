"""
工具方法
========
与具体调度算法无关的纯工具函数，从原脚本 `检定排程python代码最新8.03.py`
原样迁移，保持零修改：

- clean_columns         : DataFrame 列名清洗（去空格）
- parse_device_category : 设备描述 -> 设备分类
"""
import pandas as pd


def clean_columns(df):
    df.columns = df.columns.str.strip().str.replace(' ', '')
    return df


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
