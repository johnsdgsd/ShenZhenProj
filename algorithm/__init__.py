"""
algorithm — 核心调度算法包
============================
- constants : 算法默认参数（SchedulingConfig）
- scheduler : 核心算法函数（从原脚本 检定排程python代码最新8.03.py 原样迁移，零修改）
- prepare   : 算法输入准备（process_data，把 DataFrame 填充到 scheduler 全局变量）
- pipeline  : 统一执行流水线（CLI / HTTP 共用）

注意：scheduler 使用模块级全局变量（有状态、非重入）。算法**串行同步运行**，
不支持并发/异步 —— server 以单线程模式启动，请求按到达顺序串行处理。
"""
