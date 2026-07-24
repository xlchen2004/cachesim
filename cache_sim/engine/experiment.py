"""实验编排。

根据实验配置（算法集合、数据集、缓存容量组合）批量调度模拟器，
遍历 算法 × 数据集 × 缓存容量 组合运行模拟，并可选地运行 Belady 基线以回填竞争比。
启动时对每个文件型 trace 做一次完整性检查。
"""

from pathlib import Path
from typing import Callable, List, Optional

from cache_sim.algorithms.registry import get_algorithm
from cache_sim.config.schema import AlgorithmConfig, DatasetConfig, ExperimentConfig
from cache_sim.core.models import SimulationResult
from cache_sim.datasets.loader import check_trace, find_dataset_path, iter_requests
from cache_sim.datasets.synthetic import SyntheticGenerator
from cache_sim.engine.simulator import (
    BitModelOnlineSimulator, ContentSimulator,
    compute_bit_cost_ratio, compute_competitive_ratio,
)


class ExperimentRunner:
    """实验运行器：遍历 算法 × 数据集 × 缓存容量 组合运行模拟。"""

    def __init__(self, config: ExperimentConfig):
        self.config = config

    # ---- trace 路径解析 ----
    def _resolve_path(self, ds_cfg: DatasetConfig) -> Optional[Path]:
        """返回文件型 trace 的路径；合成数据集返回 None。"""
        if ds_cfg.source == "synthetic":
            return None
        if ds_cfg.source:
            path = Path(ds_cfg.source)
            if path.exists():
                return path
        # source 为空或路径不存在时按 name 解析内置数据集路径
        return find_dataset_path(ds_cfg.name) or find_dataset_path(ds_cfg.name, "test")

    # ---- trace 工厂 ----
    def _trace_factory(self, ds_cfg: DatasetConfig) -> Callable:
        """返回一个无参可调用对象，每次调用产出一条全新的 trace 迭代器。"""
        if ds_cfg.source == "synthetic":
            trace = SyntheticGenerator.gen_content(
                num_objects=ds_cfg.num_pages, length=ds_cfg.length,
                size_range=tuple(ds_cfg.size_range), seed=ds_cfg.seed)
            return lambda: iter(trace)
        path = self._resolve_path(ds_cfg)
        if path is None:
            raise FileNotFoundError(f"找不到数据集: {ds_cfg.source or ds_cfg.name}")
        return lambda: iter_requests(path)

    def _check_integrity(self, path: Optional[Path]) -> None:
        """启动时对文件型 trace 做完整性检查（合成数据集跳过）。违例抛 ValueError。"""
        if not self.config.integrity_check or path is None:
            return
        check_trace(path)

    # ---- 单次运行 ----
    def _run_one(self, alg_cfg: AlgorithmConfig, ds_cfg: DatasetConfig,
                 cache_size: int, rep: int) -> Optional[SimulationResult]:
        trace_factory = self._trace_factory(ds_cfg)
        policy = get_algorithm(alg_cfg.name, **alg_cfg.params)
        is_dist = getattr(policy, "distribution_based", False)

        if is_dist:
            sim = BitModelOnlineSimulator(policy, capacity=cache_size,
                                          dataset_name=ds_cfg.name)
        else:
            sim = ContentSimulator(policy, capacity=cache_size,
                                   cost_model=ds_cfg.cost_model, dataset_name=ds_cfg.name)
        result = sim.run(trace_factory())

        # 竞争比：运行 Belady 基线（在线算法才有意义）；Belady 始终走 ContentSimulator
        competitive = self.config.competitive or ds_cfg.competitive
        if competitive and not getattr(policy, "offline", False):
            belady = get_algorithm("belady")
            belady_sim = ContentSimulator(
                belady, capacity=cache_size,
                cost_model=ds_cfg.cost_model, dataset_name=ds_cfg.name)
            belady_result = belady_sim.run(trace_factory())
            if is_dist:
                result.competitive_ratio = compute_bit_cost_ratio(result, belady_result)
            else:
                result.competitive_ratio = compute_competitive_ratio(result, belady_result)
        elif getattr(policy, "offline", False):
            result.competitive_ratio = 1.0

        if self.config.repeats > 1:
            result.algorithm = f"{alg_cfg.name}#{rep}"
        return result

    def run(self) -> List[SimulationResult]:
        """运行全部实验组合。"""
        results = []
        for ds_cfg in self.config.datasets:
            # 启动完整性检查（每数据集一次；合成数据集跳过）
            path = None if ds_cfg.source == "synthetic" else self._resolve_path(ds_cfg)
            try:
                self._check_integrity(path)
            except ValueError as e:
                print(f"跳过数据集 {ds_cfg.name}：完整性检查失败（{e}）")
                continue
            for alg_cfg in self.config.algorithms:
                for cache_size in self.config.cache_sizes:
                    for rep in range(self.config.repeats):
                        try:
                            result = self._run_one(alg_cfg, ds_cfg, cache_size, rep)
                        except (ValueError, FileNotFoundError) as e:
                            print(f"跳过: 算法={alg_cfg.name}, 数据集={ds_cfg.name}, "
                                  f"k={cache_size}（{e}）")
                            continue
                        if result is not None:
                            results.append(result)
        return results

    def run_and_report(self) -> List[SimulationResult]:
        """运行实验并输出报告（JSON + CSV + 控制台摘要）。"""
        from cache_sim.metrics.report import ReportGenerator
        results = self.run()
        out_dir = Path(self.config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        prefix = self.config.output_prefix
        ReportGenerator.to_json(results, out_dir / f"{prefix}.json")
        ReportGenerator.to_csv(results, out_dir / f"{prefix}.csv")
        ReportGenerator.print_summary(results)
        return results
