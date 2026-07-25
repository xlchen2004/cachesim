"""数据集加载器与注册表（对象级缓存）。

加载空格分隔的 (time, id, size[, extra]) 对象级 trace，并提供数据集定位与
启动完整性检查。trace 数据文件置于项目根的 ``traces/`` 目录下。
"""

from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple, Union

from cache_sim.traceparser.reader import Access, ContentTraceReader, check_trace

# 数据集根目录：项目根 / traces（本模块位于 cache_sim/traceparser/loader.py，
# parents[2] 即项目根）
DATASETS_DIR = Path(__file__).resolve().parents[2] / "traces"

# 已知的对象级缓存数据集名称（均按 (time, id, size[, extra]) 格式存储）
KNOWN_DATASETS: Tuple[str, ...] = ("twitter29",)


def iter_requests(path: Union[str, Path]) -> Iterator[Access]:
    """惰性迭代 (time, id, size, extra) 请求记录。"""
    return iter(ContentTraceReader(path))


def find_dataset_path(name: str, split: str = "train") -> Optional[Path]:
    """按数据集名称与 split 定位 trace 文件。

    兼容两种 ``traces/`` 布局：扁平（``traces/<name>_<split>.csv``）与子目录
    （``traces/<name>/<name>_<split>.csv``）。

    Args:
        name: 数据集名称（如 "twitter29"）。
        split: 文件后缀（如 "train"、"test"、"valid"、"all"、"test10"）。

    Returns:
        文件路径；找不到返回 None。
    """
    name = name.lower()
    if name == "twitter29":
        # twitter29_all.csv 体积巨大（76GB），优先使用切分出的小样本
        # twitter29_test10.csv（前 10 万行）；找不到样本时退回按 split 查找。
        candidates = [
            DATASETS_DIR / "twitter29_test10.csv",                 # 扁平
            DATASETS_DIR / f"twitter29_{split}.csv",               # 扁平
            DATASETS_DIR / "twitter29" / "twitter29_test10.csv",   # 子目录
            DATASETS_DIR / "twitter29" / f"twitter29_{split}.csv",
        ]
    else:
        candidates = [
            DATASETS_DIR / f"{name}_{split}.csv",                  # 扁平
            DATASETS_DIR / f"{name}_{split}_0.01.csv",             # 扁平，小样本兜底
            DATASETS_DIR / name / f"{name}_{split}.csv",           # 子目录
            DATASETS_DIR / name / f"{name}_{split}_0.01.csv",
        ]
    for c in candidates:
        if c.exists():
            return c
    # 兜底：扁平布局下取任意匹配 split 的文件
    matches = sorted(DATASETS_DIR.glob(f"{name}_{split}*.csv"))
    if matches:
        return matches[0]
    # 兜底：子目录布局下取任意匹配 split 的文件
    d = DATASETS_DIR / name
    if d.is_dir():
        matches = sorted(d.glob(f"{name}_{split}*.csv"))
        if matches:
            return matches[0]
    return None


def list_datasets() -> Dict[str, bool]:
    """返回所有已知数据集（均为对象级缓存，值为 True）。"""
    return {name: True for name in KNOWN_DATASETS}


__all__ = [
    "DATASETS_DIR",
    "KNOWN_DATASETS",
    "iter_requests",
    "find_dataset_path",
    "list_datasets",
    "check_trace",
    "ContentTraceReader",
]
