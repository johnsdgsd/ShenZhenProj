"""
算法模块基类
============
AlgorithmModule 数据类：描述一个算法域模块的契约。

每个算法域（detect 检定 / arrival 到货 / distribution 配送）是一个自包含包，
在包 __init__.py 里声明一个 MODULE = AlgorithmModule(...)（未接入 HTTP 的骨架为 None）。
server / cli 通过 modules.all_modules() / get_module(name) 统一发现与分发，
新增算法模块无需改动 server / cli 本体。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class AlgorithmModule:
    """一个算法域模块的注册信息。

    :param name:            模块唯一名（英文小写，用于 --module 分发 / 蓝图名）
    :param display_name:    展示名（日志用，中文）
    :param interface_path:  HTTP 接口路径；None 表示本模块暂未接入 HTTP（骨架）
    :param input_sets:      HTTP 入参集合名（仅日志统计用，不参与解析）
    :param output_key:      出参 JSON 顶层 key（如 detectPlanSchedulingchList）
    :param config:          DataSourceConfig 类（Excel 兑底 sheet 映射 / 输出路径）
    :param reader:          reader 模块（提供 read_excel / read_json）
    :param pipeline:        pipeline 模块（提供 run_pipeline）
    :param writer:          writer 模块（提供 write_excel / write_json）
    """
    name: str
    display_name: str
    interface_path: str | None
    input_sets: tuple
    output_key: str
    config: object = None
    reader: object = None
    pipeline: object = None
    writer: object = None

    def is_http(self) -> bool:
        """是否已接入 HTTP 接口。"""
        return self.interface_path is not None
