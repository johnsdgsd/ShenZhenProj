"""
配送模块（骨架，未实现算法）
============================
预留命名空间。仓库目前**没有任何配送参考算法**——"配送"只出现在
合格品库存的「未配送库存」列（distLockQty），检定排程把它们从可用库存中扣减。

接入时需先与业务方确认配送算法输入模型（单据/台账等），
再按 modules/detect/ 的包结构新建本目录下的实现文件，
并把 MODULE 从 None 改为 AlgorithmModule(name='distribution', ...)。

MODULE = None：骨架占位，不进入注册表、不暴露 HTTP、不可被 --module 分发。
"""
from modules.base import AlgorithmModule

MODULE = None  # type: ignore[assignment]
