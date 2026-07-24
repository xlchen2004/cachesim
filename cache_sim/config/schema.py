"""实验配置 schema。

定义实验配置的数据类，包括算法配置、数据集配置与实验整体配置。
仅适配对象级缓存（Content Cache）。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AlgorithmConfig:
    """算法配置。"""
    name: str                                                # 算法注册名
    params: Dict[str, Any] = field(default_factory=dict)    # 算法参数


@dataclass
class DatasetConfig:
    """数据集配置（对象级缓存）。

    source 为 "synthetic" 时生成合成 trace；为文件路径时直接读取；
    为空时按 name 解析内置数据集路径（如 twitter29）。
    """
    name: str                                  # 数据集名称（用于报告与路径解析）
    source: str = ""                           # 文件路径 / "synthetic" / 数据集名；空则按 name 解析
    # 对象级参数
    cost_model: str = "bit"                     # bit / fault / general
    # 合成数据集参数
    num_pages: int = 100
    length: int = 1000
    size_range: List[int] = field(default_factory=lambda: [1, 1000])
    seed: Optional[int] = None
    # 是否为本数据集运行 Belady 基线计算竞争比
    competitive: bool = False


@dataclass
class ExperimentConfig:
    """实验配置。"""
    algorithms: List[AlgorithmConfig] = field(default_factory=list)
    datasets: List[DatasetConfig] = field(default_factory=list)
    cache_sizes: List[int] = field(default_factory=lambda: [1000])  # 扫描的缓存容量（字节）
    repeats: int = 1                           # 重复次数（用于随机算法）
    output_dir: str = "results"
    output_prefix: str = "experiment"
    competitive: bool = False                  # 全局竞争比开关
    integrity_check: bool = True               # 启动时对 trace 做完整性检查
