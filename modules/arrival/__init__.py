"""
到货排程模块（骨架，未实现算法）
================================
预留命名空间：后续接入 到货排程算法（参考 docs/算法脚本/到货排程/8.13/8.14）。

与检定模块不同，到货排程的输入模型完全不同，需要**新的接口集合**，当前报文
（deviceParaList / dmdPlanDetList 等 9 集合）提供不了，0812 报文无法构造其输入：
  - 月度需用（按物资编码）
  - 订单合同清单
  - 供应商信息
  - 已供货通知物资
  - 库区容量 / 库房排程时间
  - 合格品库存详情 / 非合格品库存详情

实现时：新建 modules/arrival/ 下的 constants / reader / scheduler / prepare /
pipeline / writer / extractor，把本文件 MODULE 从 None 改为
AlgorithmModule(name='arrival', interface_path='<待定接口路径>', ...)，
并在 modules/__init__.py 保持 import（自动注册）。

MODULE = None：骨架占位，不进入注册表、不暴露 HTTP、不可被 --module 分发。
"""
from modules.base import AlgorithmModule

MODULE = None  # type: ignore[assignment]
