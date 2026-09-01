"""V0.0.6 到货计划排程 JSON 入参读取器。"""
from __future__ import annotations

import logging
from typing import Dict

import pandas as pd

from .constants import INPUT_SETS

logger = logging.getLogger(__name__)


def read_json(data: dict) -> Dict[str, pd.DataFrame]:
    """校验八个顶层集合，并转换为同名 DataFrame。"""
    if not isinstance(data, dict):
        logger.warning('到货请求不是 JSON 对象: %s', type(data).__name__)
        raise TypeError('请求 JSON 必须是对象')

    frames: Dict[str, pd.DataFrame] = {}
    for name in INPUT_SETS:
        if name not in data:
            logger.warning('到货请求缺少必填集合: %s', name)
            raise ValueError(f'缺少必填集合: {name}')
        value = data[name]
        if not isinstance(value, list):
            logger.warning('到货请求集合 %s 不是数组', name)
            raise TypeError(f'{name} 必须是数组')
        frames[name] = pd.DataFrame(value)

    logger.info(
        '到货接口 JSON 读取完成：%s',
        ', '.join(f'{name}={len(frames[name])}' for name in INPUT_SETS),
    )
    return frames
