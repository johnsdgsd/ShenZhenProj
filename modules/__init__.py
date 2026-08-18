"""
算法模块注册中心
================
每个算法域一个自包含包（modules/<域>/），在包 __init__.py 里声明 MODULE。
本文件 import 各子包，收集 MODULE（非 None）进注册表：

- all_modules()  -> 全部已注册模块列表（server 遍历注册蓝图、cli 分发用）
- get_module(name) -> 按名称取模块

新增算法模块：新建 modules/<域>/ 包 + 在本文件 import 并声明，自动被发现。
骨架模块（MODULE=None，如到货/配送）不进入注册表，仅预留命名空间。
"""
from __future__ import annotations

from . import arrival, detect, distribution  # noqa: F401  (import 即注册)

_MODULES = {}


def _collect() -> None:
    for _pkg in (detect, arrival, distribution):
        mod = getattr(_pkg, 'MODULE', None)
        if mod is not None:
            _MODULES[mod.name] = mod


_collect()


def all_modules():
    """返回全部已注册算法模块（按包声明顺序）。"""
    return list(_MODULES.values())


def get_module(name: str):
    """按名称取算法模块；未注册时抛 ValueError 并列出可选名。"""
    try:
        return _MODULES[name]
    except KeyError:
        raise ValueError(
            f"未知算法模块: {name}，可选: {', '.join(_MODULES) or '(无已注册模块)'}"
        ) from None
