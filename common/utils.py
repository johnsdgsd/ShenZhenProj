"""
工具方法
========
与具体调度算法无关的纯工具函数，从原脚本 `检定排程python代码最新8.03.py`
原样迁移，保持零修改：

- clean_columns : DataFrame 列名清洗（去空格）

注：parse_device_category 已迁入 modules/detect/category.py（8.16 版，
含低压电流互感器子类型 + VW_DETECT_EQUIP_TYPE 码值适配），不再放在公共层——它属于检定算法域。
"""
import pandas as pd


def clean_columns(df):
    df.columns = df.columns.str.strip().str.replace(' ', '')
    return df
