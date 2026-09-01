"""到货计划排程 HTTP 模块（8.24 算法基线 / V0.0.6 接口）。"""
from modules.base import AlgorithmModule

from . import pipeline, reader, writer
from .constants import INPUT_SETS


MODULE = AlgorithmModule(
    name='arrival',
    display_name='到货计划排程',
    interface_path='/restful/busiInterface/ipsService/arrivePlanScheduling',
    input_sets=INPUT_SETS,
    output_key='arrivePlanSchedulingchList',
    reader=reader,
    pipeline=pipeline,
    writer=writer,
)
