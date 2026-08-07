"""
data — 数据处理层包
====================
- constants : 接口枚举字典（来自接口说明.md）+ Excel 兑底 sheet 映射（DataSourceConfig）
- reader    : read_excel / read_json —— 两种输入格式 → 11 个 DataFrame
- writer    : write_excel / write_json —— 输出 DataFrame → Excel / 出参 JSON

只做输入输出格式适配 + 异常处理，不做多余封装。
reader 返回同构的 {key: DataFrame}，与 algorithm/prepare.py 的 process_data()
期望一致，核心算法对两条路径完全复用。
"""
