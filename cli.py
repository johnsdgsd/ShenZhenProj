"""
命令行兑底脚本 — 离线读 Excel 出 Excel（开发 / 功能等价性验证）
================================================================
用法：
    python cli.py <输入Excel路径> [-o 输出Excel路径]
    未指定 -o 时输出到默认文件（检定排程计划_优化版_无加班.xlsx）。

生产环境请用 main.py 启动 HTTP 算法服务：python main.py
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _run(input_path: Path, output_path: Path = None) -> int:
    from algorithm.constants import SchedulingConfig
    from algorithm.pipeline import run_pipeline
    from data.constants import DataSourceConfig
    from data.reader import read_excel
    from data.writer import write_excel

    sched_cfg = SchedulingConfig()
    ds_cfg = DataSourceConfig()
    try:
        dfs = read_excel(input_path, ds_cfg.input_sheet_names)
        output_dfs = run_pipeline(dfs, sched_cfg)
        path = write_excel(output_dfs, output_path or ds_cfg.output_path, ds_cfg.output_sheet_names)
        logger.info("排程完成！结果保存至: %s", path)
        return 0
    except Exception:
        logger.exception("排程执行失败")
        return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='检定排程 Excel 兑底（离线开发/验证）')
    parser.add_argument('input', help='输入 Excel 文件路径（11 个 sheet）')
    parser.add_argument('-o', '--output', help='输出 Excel 文件路径（默认：检定排程计划_优化版_无加班.xlsx）')
    args = parser.parse_args(argv)

    from common.logging_utils import setup_logging
    setup_logging()

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else None
    return _run(input_path, output_path)


if __name__ == '__main__':
    sys.exit(main())
