"""
命令行兑底脚本 — 离线读 Excel 出 Excel（开发 / 功能等价性验证）
================================================================
用法：
    python cli.py <输入Excel路径> [-o 输出Excel路径] [--module detect]
    未指定 -o 时输出到模块默认文件。
    --module 指定算法模块（默认 detect，见 modules 注册中心），
    后续接入到货/配送后可用 --module arrival 等分发。

生产环境请用 main.py 启动 HTTP 算法服务：python main.py
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _run(input_path: Path, output_path: Path = None, module_name: str = 'detect') -> int:
    from modules import get_module

    mod = get_module(module_name)
    ds_cfg = mod.config()
    try:
        dfs = mod.reader.read_excel(input_path, ds_cfg.input_sheet_names)
        output_dfs = mod.pipeline.run_pipeline(dfs)
        path = mod.writer.write_excel(output_dfs, output_path or ds_cfg.output_path, ds_cfg.output_sheet_names)
        logger.info("%s排程完成！结果保存至: %s", mod.display_name, path)
        return 0
    except Exception:
        logger.exception("%s排程执行失败", mod.display_name)
        return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='算法 Excel 兑底（离线开发/验证）')
    parser.add_argument('input', help='输入 Excel 文件路径（算法模块要求的全部 sheet）')
    parser.add_argument('-o', '--output', help='输出 Excel 文件路径（默认取模块默认输出路径）')
    parser.add_argument('--module', default='detect',
                        help='算法模块名（默认 detect；可选见 modules 注册中心）')
    args = parser.parse_args(argv)

    from common.logging_utils import setup_logging
    setup_logging()

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else None
    return _run(input_path, output_path, args.module)


if __name__ == '__main__':
    sys.exit(main())
