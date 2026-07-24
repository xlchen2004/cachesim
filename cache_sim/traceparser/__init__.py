"""datasets 子包：对象级缓存 trace 读取、合成生成与完整性检查。"""

from cache_sim.datasets.reader import (
    Access,
    ContentTraceReader,
    TwitterReader,
    check_trace,
)
from cache_sim.datasets.loader import (
    DATASETS_DIR,
    KNOWN_DATASETS,
    iter_requests,
    find_dataset_path,
    list_datasets,
)
from cache_sim.datasets.synthetic import SyntheticGenerator

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
