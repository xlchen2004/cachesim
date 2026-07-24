"""实验配置加载器。

支持从 JSON 或 YAML 文件加载实验配置，并解析为 ExperimentConfig 数据类。
"""

import json
from pathlib import Path
from typing import Union

from cache_sim.config.schema import (
    AlgorithmConfig,
    DatasetConfig,
    ExperimentConfig,
)


def load_config(path: Union[str, Path]) -> ExperimentConfig:
    """加载 YAML 或 JSON 配置文件。"""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            raise ImportError("加载 YAML 配置需要 pyyaml：pip install pyyaml")
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return parse_config(data)


def parse_config(data: dict) -> ExperimentConfig:
    """从字典解析实验配置。"""
    algorithms = [
        AlgorithmConfig(name=a["name"], params=a.get("params", {}))
        for a in data.get("algorithms", [])
    ]
    datasets = [
        DatasetConfig(
            name=d["name"],
            source=d.get("source", ""),
            cost_model=d.get("cost_model", "bit"),
            num_pages=d.get("num_pages", 100),
            length=d.get("length", 1000),
            size_range=d.get("size_range", [1, 1000]),
            seed=d.get("seed"),
            competitive=d.get("competitive", False),
        )
        for d in data.get("datasets", [])
    ]
    return ExperimentConfig(
        algorithms=algorithms,
        datasets=datasets,
        cache_sizes=data.get("cache_sizes", [1000]),
        repeats=data.get("repeats", 1),
        output_dir=data.get("output_dir", "results"),
        output_prefix=data.get("output_prefix", "experiment"),
        competitive=data.get("competitive", False),
        integrity_check=data.get("integrity_check", True),
    )
