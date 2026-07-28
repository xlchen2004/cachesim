"""批量实验：4 数据集 x {1%,2%,5%,10% 总字节} 缓存大小 x {belady, lru, bit_model_online}。

缓存大小按各数据集总字节数的百分比计算（四舍五入到整数字节）。每个 (数据集,
缓存大小) 只运行一次 Belady 基线并复用于 LRU / bit_model_online 的竞争比计算。
结果逐条保存到 results/multi/ 下的 JSON；本脚本可断点续跑——已存在的结果文件会
被直接加载，仅补算缺失的配置，最后打印完整 Markdown 表格供 README 使用。

用法: python run_experiments.py
"""

import json
import time
from pathlib import Path

from cache_sim.algorithms.registry import get_algorithm
from cache_sim.core.models import SimulationResult
from cache_sim.engine.simulator import (
    BitModelOnlineSimulator, ContentSimulator,
    compute_byte_competitive_ratio, compute_competitive_ratio,
)
from cache_sim.traceparser.loader import check_trace, iter_requests

DATASETS = [
    "synthetic_test.csv",
    "twitter29_test10.csv",
    "twitter45_test.csv",
    "wiki2018_test10.csv",
]
PCTS = [1, 2, 5, 10]
ALGORITHMS = ["belady", "lru", "bit_model_online"]
TRACE_DIR = Path("traces")
OUT_DIR = Path("results/multi")
SEED = 42

# SimulationResult 的构造字段（hit_rate / bhr 是派生属性，不传入构造函数）
_RESULT_FIELDS = (
    "cache_type", "algorithm", "dataset", "config", "total_requests", "hits",
    "misses", "byte_total", "byte_hit", "evictions", "competitive_ratio",
    "byte_competitive_ratio", "extra",
)


def trace_factory(path):
    return lambda: iter_requests(path)


def run_one(alg_name, path, capacity, dataset_name, cost_model="bit"):
    """运行单个 (算法, 数据集, 缓存大小)，返回 SimulationResult。"""
    if alg_name == "bit_model_online":
        policy = get_algorithm(alg_name, seed=SEED)
        sim = BitModelOnlineSimulator(policy, capacity=capacity, dataset_name=dataset_name)
    else:
        policy = get_algorithm(alg_name)
        sim = ContentSimulator(policy, capacity=capacity,
                               cost_model=cost_model, dataset_name=dataset_name)
    return sim.run(trace_factory(path)())


def _fname(ds, pct, alg):
    return f"{Path(ds).stem}_pct{pct}_{alg}.json"


def _load(ds, pct, alg):
    """从已保存的 JSON 加载 SimulationResult；文件不存在返回 None。"""
    p = OUT_DIR / _fname(ds, pct, alg)
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    kwargs = {k: d[k] for k in _RESULT_FIELDS if k in d}
    return SimulationResult(**kwargs)


def _save(res, ds, pct, alg):
    (OUT_DIR / _fname(ds, pct, alg)).write_text(res.to_json(), encoding="utf-8")


def get_result(alg, ds, path, capacity, pct, belady_res):
    """取单个配置的结果：已有 JSON 则加载，否则运行、保存并回填竞争比。"""
    cached = _load(ds, pct, alg)
    if cached is not None:
        return cached, True
    res = run_one(alg, path, capacity, ds)
    if alg == "belady":
        res.competitive_ratio = 1.0
        res.byte_competitive_ratio = 1.0
    else:
        res.competitive_ratio = compute_competitive_ratio(res, belady_res)
        res.byte_competitive_ratio = compute_byte_competitive_ratio(res, belady_res)
    _save(res, ds, pct, alg)
    return res, False


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_rows = []
    for ds in DATASETS:
        path = TRACE_DIR / ds
        stats = check_trace(path)
        total_bytes = stats["total_bytes"]
        print(f"\n=== {ds} === 请求={stats['num_requests']} 唯一对象="
              f"{stats['num_unique_objects']} 总字节={total_bytes} "
              f"大小=[{stats['min_size']},{stats['max_size']}]", flush=True)
        for pct in PCTS:
            capacity = int(round(total_bytes * pct / 100.0))
            # Belady 基线
            belady_res, cached = get_result("belady", ds, path, capacity, pct, None)
            if not cached:
                print(f"  [{pct}%] capacity={capacity} belady 完成 "
                      f"misses={belady_res.misses} "
                      f"byte_miss={belady_res.byte_total-belady_res.byte_hit}",
                      flush=True)
            all_rows.append((ds, pct, capacity, belady_res))

            for alg in ("lru", "bit_model_online"):
                t0 = time.time()
                res, cached = get_result(alg, ds, path, capacity, pct, belady_res)
                tag = "加载" if cached else "完成"
                if not cached:
                    print(f"  [{pct}%] capacity={capacity} {alg} {tag} "
                          f"({time.time()-t0:.1f}s) ocr={res.competitive_ratio:.4f} "
                          f"bcr={res.byte_competitive_ratio:.4f}", flush=True)
                else:
                    print(f"  [{pct}%] capacity={capacity} {alg} {tag} "
                          f"ocr={res.competitive_ratio:.4f} "
                          f"bcr={res.byte_competitive_ratio:.4f}", flush=True)
                all_rows.append((ds, pct, capacity, res))

    _print_markdown(all_rows)
    print(f"\n所有结果已保存至 {OUT_DIR}/")


def _print_markdown(rows):
    """按数据集分组打印 Markdown 表格。"""
    print("\n\n========== Markdown 表格 ==========\n")
    datasets = []
    for ds, _, _, _ in rows:
        if ds not in datasets:
            datasets.append(ds)
    for ds in datasets:
        total_bytes = check_trace(TRACE_DIR / ds)["total_bytes"]
        print(f"### {ds}（总字节 {total_bytes}）\n")
        print("| 缓存比例 | 缓存大小 | 算法 | 命中 | 未命中 | OHR | 字节命中 | BHR | "
              "驱逐 | fetch_cost | 对象数竞争比 | 字节数竞争比 |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for d, pct, cap, r in rows:
            if d != ds:
                continue
            fc = r.extra.get("fetch_cost") if r.extra else None
            fc_s = f"{fc:.0f}" if fc is not None else "-"
            ocr = f"{r.competitive_ratio:.4f}" if r.competitive_ratio is not None else "-"
            bcr = (f"{r.byte_competitive_ratio:.4f}"
                   if r.byte_competitive_ratio is not None else "-")
            print(f"| {pct}% | {cap} | {r.algorithm} | {r.hits} | {r.misses} | "
                  f"{r.ohr:.4f} | {r.byte_hit} | {r.bhr:.4f} | {r.evictions} | "
                  f"{fc_s} | {ocr} | {bcr} |")
        print()


if __name__ == "__main__":
    main()
