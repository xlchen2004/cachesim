"""traceparser 子包：对象级缓存 trace 生成、读取与完整性检查。

``basic_trace`` 是 ``basic_trace.cc`` 的忠实 Python 复现，见
:mod:`cache_sim.traceparser.basic_trace`（直接 ``from cache_sim.traceparser.basic_trace
import generate_basic_trace`` 使用；此处不预先导入，以免 ``python -m
cache_sim.traceparser.basic_trace`` 独立运行时产生告警）。
"""

from cache_sim.traceparser.reader import (
    Access,
    ContentTraceReader,
    TwitterReader,
    check_trace,
)
from cache_sim.traceparser.loader import (
    DATASETS_DIR,
    KNOWN_DATASETS,
    iter_requests,
    find_dataset_path,
    list_datasets,
)
from cache_sim.traceparser.tracegenerator import SyntheticGenerator

__all__ = [
    "Access",
    "ContentTraceReader",
    "TwitterReader",
    "check_trace",
    "DATASETS_DIR",
    "KNOWN_DATASETS",
    "iter_requests",
    "find_dataset_path",
    "list_datasets",
    "SyntheticGenerator",
]
