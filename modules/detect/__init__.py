"""
检定排程算法模块（8.28 核心）
============================
自包含包：数据层（reader/writer/extractor）+ 算法层（scheduler/prepare/pipeline）+ 常量。

本文件声明 MODULE = AlgorithmModule(...)，供 modules 注册中心发现：
- server 据此自动注册 HTTP 蓝图（interface_path）
- cli 据此支持 --module detect 离线兑底
"""
from modules.base import AlgorithmModule

from . import pipeline, reader, writer  # noqa: F401  (模块对象供 AlgorithmModule 引用)
from .constants import DataSourceConfig

MODULE = AlgorithmModule(
    name='detect',
    display_name='检定排程',
    interface_path='/restful/busiInterface/ipsService/detectPlanScheduling',
    input_sets=(
        'deviceParaList', 'dmdPlanDetList', 'arriveBatchList', 'detectSchList',
        'qualifiedStockList', 'unqualifiedStockList', 'scheduleTimeList',
        'scheduleConfigList', 'nonDmdAimEquipCodeCfgList',
    ),
    output_key='detectPlanSchedulingchList',
    config=DataSourceConfig,
    reader=reader,
    pipeline=pipeline,
    writer=writer,
)
