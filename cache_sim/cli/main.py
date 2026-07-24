"""命令行入口。

支持三种子命令（首 token 分派）：
  1. ``python -m cache_sim --config experiment.yaml`` 或
     ``python -m cache_sim --algorithm lru --dataset twitter29 --capacity 1000``
     —— 运行模拟（单次 / 配置文件批量）。
  2. ``python -m cache_sim gen-trace ...`` —— 生成 Pareto/Bounded-Pareto 合成 trace。
  3. ``python -m cache_sim check-trace <path>`` —— 对 trace 做完整性检查并打印统计。

仅支持对象级缓存（Content Cache）。
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from cache_sim.algorithms.registry import get_algorithm, list_algorithms
from cache_sim.config.loader import load_config
from cache_sim.datasets.loader import check_trace, find_dataset_path, iter_requests
from cache_sim.datasets.synthetic import SyntheticGenerator
from cache_sim.engine.simulator import (
    BitModelOnlineSimulator, ContentSimulator,
    compute_bit_cost_ratio, compute_competitive_ratio,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cache_sim",
        description="对象级缓存模拟框架，支持多种驱逐策略。",
    )
    parser.add_argument("--config", "-c", type=str, default=None,
                        help="实验配置文件路径（YAML/JSON），批量实验")
    parser.add_argument("--algorithm", "-a", type=str, default=None,
                        help=f"算法名称（可选: {', '.join(list_algorithms())}）")
    parser.add_argument("--dataset", "-d", type=str, default=None,
                        help="数据集文件路径、名称（如 twitter29）或 'synthetic'")
    # 对象级参数
    parser.add_argument("--capacity", type=int, default=None,
                        help="对象级缓存总容量（字节）")
    parser.add_argument("--cost-model", type=str, default="bit",
                        choices=["bit", "fault", "general"],
                        help="对象级缓存成本模型（默认 bit）")
    # 通用
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="输出报告路径（JSON/CSV）")
    parser.add_argument("--seed", type=int, default=None, help="随机种子")
    parser.add_argument("--competitive", action="store_true",
                        help="运行 Belady 基线并计算竞争比")
    parser.add_argument("--no-integrity-check", action="store_true",
                        help="跳过启动时的 trace 完整性检查")
    # 合成数据集参数
    parser.add_argument("--num-pages", type=int, default=100,
                        help="合成数据集对象数（默认 100）")
    parser.add_argument("--length", type=int, default=1000,
                        help="合成数据集请求序列长度（默认 1000）")
    parser.add_argument("--size-range", type=int, nargs=2, default=[1, 1000],
                        help="合成对象级数据集对象大小范围（默认 1 1000）")
    parser.add_argument("--list-algorithms", action="store_true",
                        help="列出所有已注册的算法并退出")
    return parser


def _print_result(result) -> None:
    print(f"\n=== 模拟结果 ===")
    print(f"算法: {result.algorithm}")
    print(f"数据集: {result.dataset}")
    print(f"缓存类型: {result.cache_type}")
    cfg = result.config
    print(f"capacity: {cfg.get('capacity')}, cost_model: {cfg.get('cost_model')}")
    print(f"访问总次数: {result.total_requests}")
    print(f"命中数: {result.hits} (OHR: {result.ohr:.4f})")
    print(f"未命中数: {result.misses}")
    print(f"字节总流量: {result.byte_total}, 字节命中: {result.byte_hit} (BHR: {result.bhr:.4f})")
    fc = result.extra.get("fetch_cost") if result.extra else None
    if fc is not None:
        print(f"bit-model 取回代价: {fc}")
    print(f"驱逐次数: {result.evictions}")
    if result.competitive_ratio is not None:
        print(f"竞争比: {result.competitive_ratio:.4f}")


def _resolve_path(dataset: str) -> Optional[Path]:
    """数据集名/路径 -> 文件路径；synthetic 返回 None。"""
    if dataset == "synthetic":
        return None
    path = Path(dataset)
    if path.exists():
        return path
    return find_dataset_path(Path(dataset).name) or find_dataset_path(Path(dataset).name, "test")


def _trace_factory(args, path: Optional[Path]):
    """构造可重复遍历的 trace 工厂。"""
    if args.dataset == "synthetic":
        trace = SyntheticGenerator.gen_content(
            num_objects=args.num_pages, length=args.length,
            size_range=tuple(args.size_range), seed=args.seed)
        return lambda: iter(trace)
    if path is None:
        return None
    return lambda: iter_requests(path)


def _simulate(args, policy, dataset_name, trace_factory):
    is_dist = getattr(policy, "distribution_based", False)
    capacity = args.capacity
    if capacity is None:
        print("错误：对象级缓存需要指定 --capacity", file=sys.stderr)
        sys.exit(1)
    if is_dist:
        sim = BitModelOnlineSimulator(policy, capacity=capacity, dataset_name=dataset_name)
    else:
        sim = ContentSimulator(policy, capacity=capacity,
                               cost_model=args.cost_model, dataset_name=dataset_name)
    return sim.run(trace_factory())


def run_single(args) -> None:
    if not args.algorithm:
        print("错误：单次运行模式需要指定 --algorithm", file=sys.stderr)
        sys.exit(1)
    if not args.dataset:
        print("错误：单次运行模式需要指定 --dataset", file=sys.stderr)
        sys.exit(1)

    dataset_name = args.dataset
    path = _resolve_path(args.dataset)

    # 启动完整性检查（文件型 trace；合成数据集跳过）
    if not args.no_integrity_check and path is not None:
        try:
            stats = check_trace(path)
            print(f"完整性检查通过: {stats['num_requests']} 条请求, "
                  f"{stats['num_unique_objects']} 个对象, "
                  f"总字节 {stats['total_bytes']}, "
                  f"对象大小 [{stats['min_size']}, {stats['max_size']}], "
                  f"extra 列数 {stats['num_extra_cols']}")
        except ValueError as e:
            print(f"错误：trace 完整性检查失败（{e}）", file=sys.stderr)
            sys.exit(1)

    trace_factory = _trace_factory(args, path)
    if trace_factory is None:
        print(f"错误：找不到数据集 {args.dataset}", file=sys.stderr)
        sys.exit(1)

    if args.algorithm == "bit_model_online":
        policy = get_algorithm(args.algorithm, seed=args.seed)
    else:
        policy = get_algorithm(args.algorithm)
    result = _simulate(args, policy, dataset_name, trace_factory)

    is_dist = getattr(policy, "distribution_based", False)
    if args.competitive and not getattr(policy, "offline", False):
        belady = get_algorithm("belady")
        belady_result = _simulate(args, belady, dataset_name, trace_factory)
        if is_dist:
            result.competitive_ratio = compute_bit_cost_ratio(result, belady_result)
        else:
            result.competitive_ratio = compute_competitive_ratio(result, belady_result)
        belady_result.competitive_ratio = 1.0
        print("\n--- Belady 基线 ---")
        _print_result(belady_result)
    elif getattr(policy, "offline", False):
        result.competitive_ratio = 1.0

    _print_result(result)

    if args.output:
        out_path = Path(args.output)
        if out_path.suffix.lower() == ".csv":
            from cache_sim.metrics.report import ReportGenerator
            ReportGenerator.to_csv([result], out_path)
        else:
            out_path.write_text(result.to_json(), encoding="utf-8")
        print(f"\n报告已保存至: {out_path}")


def run_config(args) -> None:
    if not args.config:
        print("错误：需要指定 --config", file=sys.stderr)
        sys.exit(1)
    config = load_config(args.config)
    config.integrity_check = not args.no_integrity_check
    from cache_sim.engine.experiment import ExperimentRunner
    runner = ExperimentRunner(config)
    runner.run_and_report()
    print(f"\n报告已保存至: {config.output_dir}/")


def run_gen_trace(argv: List[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="cache_sim gen-trace",
        description="生成 Pareto（Zipf-like）流行度 + Bounded-Pareto 大小的对象级 trace。")
    parser.add_argument("--num-objects", type=int, default=1000,
                        help="不同对象数量（默认 1000）")
    parser.add_argument("--popular-requests", type=int, default=10000,
                        help="最热门对象被请求的次数（默认 10000，总长为其倍数）")
    parser.add_argument("--pareto-shape", type=float, default=1.8,
                        help="Pareto/Zipf 流行度形状参数 α（默认 1.8）")
    parser.add_argument("--min-size", type=int, default=1, help="最小对象大小（默认 1）")
    parser.add_argument("--max-size", type=int, default=10000, help="最大对象大小（默认 10000）")
    parser.add_argument("--size-shape", type=float, default=1.0,
                        help="Bounded-Pareto 大小分布形状（默认 1.0）")
    parser.add_argument("-o", "--output", type=str, required=True, help="输出 trace 文件路径")
    parser.add_argument("--seed", type=int, default=None, help="随机种子")
    args = parser.parse_args(argv)

    trace = SyntheticGenerator.basic_trace(
        num_objects=args.num_objects, popular_requests=args.popular_requests,
        pareto_shape=args.pareto_shape, min_size=args.min_size, max_size=args.max_size,
        output_path=args.output, seed=args.seed, size_shape=args.size_shape)
    n = len(trace) if trace else None
    # 写文件时 trace 为空，用 check_trace 统计
    stats = check_trace(args.output)
    print(f"已生成 trace: {args.output}")
    print(f"  对象数: {args.num_objects}, 流行度形状: {args.pareto_shape}, "
          f"大小: [{args.min_size}, {args.max_size}]")
    print(f"  请求数: {stats['num_requests']}, 唯一对象: {stats['num_unique_objects']}, "
          f"总字节: {stats['total_bytes']}, 大小范围: "
          f"[{stats['min_size']}, {stats['max_size']}]")


def run_check_trace(argv: List[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="cache_sim check-trace",
        description="对 trace 做完整性检查并打印统计。")
    parser.add_argument("path", type=str, help="trace 文件路径")
    parser.add_argument("--max-lines", type=int, default=0,
                        help="最多检查的行数（0 = 全量）")
    args = parser.parse_args(argv)

    try:
        stats = check_trace(args.path, max_lines=args.max_lines)
    except ValueError as e:
        print(f"完整性检查失败: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"完整性检查通过: {args.path}")
    print(f"  请求数: {stats['num_requests']}")
    print(f"  唯一对象数: {stats['num_unique_objects']}")
    print(f"  总字节: {stats['total_bytes']}")
    print(f"  对象大小范围: [{stats['min_size']}, {stats['max_size']}]")
    print(f"  extra 列数: {stats['num_extra_cols']}")


def main(argv: Optional[List[str]] = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    if argv and argv[0] == "gen-trace":
        run_gen_trace(argv[1:])
        return
    if argv and argv[0] == "check-trace":
        run_check_trace(argv[1:])
        return

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_algorithms:
        print("已注册的算法:")
        for name in list_algorithms():
            print(f"  - {name}")
        return

    if args.config:
        run_config(args)
    elif args.algorithm:
        run_single(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
