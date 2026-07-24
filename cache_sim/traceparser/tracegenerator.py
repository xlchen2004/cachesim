"""合成 trace 生成器（对象级缓存）。

生成 (time, id, size, extra) 对象级 trace，便于在缺少真实 trace 时进行算法评估与测试。

提供两种生成方式：
  - :meth:`SyntheticGenerator.gen_content`：均匀 / Zipf 流行度，固定大小。
  - :meth:`SyntheticGenerator.basic_trace`：Pareto（Zipf-like）流行度 + Bounded-Pareto
    对象大小，对应项目设计.md 中描述的 ``basic_trace`` 工具。
"""

import math
import random
from typing import List, Optional, Tuple, Union

from cache_sim.datasets.reader import Access

# 一次访问记录：(time, id, size, extra)
# Access = Tuple[int, int, int, Tuple[int, ...]]


class SyntheticGenerator:
    """合成 trace 生成器。"""

    @staticmethod
    def gen_content(num_objects: int, length: int,
                    size_range: Tuple[int, int] = (1, 1000),
                    zipf: bool = False, seed: Optional[int] = None
                    ) -> List[Access]:
        """生成 (time, id, size, extra) 对象级 trace。

        Args:
            num_objects: 不同对象数量。
            length: 请求序列长度。
            size_range: 对象大小范围 (min, max)。
            zipf: 是否使用 Zipf 分布选择对象。
            seed: 随机种子。

        Returns:
            (time, id, size, extra) 四元组列表。time 即请求序号，extra 为空。
        """
        if num_objects <= 0:
            raise ValueError(f"num_objects 必须为正，得到 {num_objects}")
        if length < 0:
            raise ValueError(f"length 不能为负，得到 {length}")
        if length == 0:
            return []
        rng = random.Random(seed)
        # 每个对象固定大小
        sizes = {i: rng.randint(size_range[0], size_range[1]) for i in range(num_objects)}
        trace: List[Access] = []
        if zipf:
            cum = SyntheticGenerator._zipf_cdf(num_objects, 1.0)
        for t in range(length):
            if zipf:
                oid = SyntheticGenerator._sample_cdf(rng, cum)
            else:
                oid = rng.randint(0, num_objects - 1)
            trace.append((t, oid, sizes[oid], ()))
        return trace

    @staticmethod
    def basic_trace(num_objects: int, popular_requests: int,
                    pareto_shape: float, min_size: int, max_size: int,
                    output_path: Optional[Union[str]] = None,
                    seed: Optional[int] = None,
                    size_shape: float = 1.0) -> List[Access]:
        """生成 Pareto（Zipf-like）流行度 + Bounded-Pareto 大小的对象级 trace。

        对应项目设计.md 的 ``basic_trace`` 工具。参数：
          - num_objects: 不同对象数量。
          - popular_requests: 最热门对象被请求的次数（总请求长度为其倍数）。
          - pareto_shape: Pareto / Zipf 流行度形状参数 α（>0，越大越倾斜）。
          - min_size / max_size: 对象大小上下界（字节）。
          - output_path: 若给定则将 trace 流式写入该文件（空格分隔 `time id size`），
            此时返回空列表；否则返回内存中的 trace 列表。
          - size_shape: Bounded-Pareto 大小分布形状参数（默认 1.0）。

        示例（项目设计.md）：1000 对象、≈10000 请求、α=1.8、size 1..10000。
        """
        if num_objects <= 0:
            raise ValueError(f"num_objects 必须为正，得到 {num_objects}")
        if popular_requests <= 0:
            raise ValueError(f"popular_requests 必须为正，得到 {popular_requests}")
        if pareto_shape <= 0:
            raise ValueError(f"pareto_shape 必须为正，得到 {pareto_shape}")
        if min_size <= 0 or max_size < min_size:
            raise ValueError(f"min_size/max_size 非法: {min_size}/{max_size}")
        rng = random.Random(seed)

        # 流行度：Zipf P(i) ∝ 1/i^α，归一化；total = popular_requests / P(1)
        cum = SyntheticGenerator._zipf_cdf(num_objects, pareto_shape)
        p1 = cum[0]  # P(最热门) = cum[0]
        total = max(num_objects, int(round(popular_requests / p1)))

        # 每个对象固定大小，取自 Bounded-Pareto on [min_size, max_size]
        sizes = {i: SyntheticGenerator._bounded_pareto(
                     rng, min_size, max_size, size_shape)
                 for i in range(num_objects)}

        trace: List[Access] = []
        f = None
        if output_path is not None:
            f = open(output_path, "w", encoding="utf-8")
        try:
            for t in range(total):
                oid = SyntheticGenerator._sample_cdf(rng, cum)
                sz = sizes[oid]
                if f is not None:
                    f.write(f"{t} {oid} {sz}\n")
                else:
                    trace.append((t, oid, sz, ()))
        finally:
            if f is not None:
                f.close()
        return trace

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _zipf_cdf(n: int, alpha: float) -> List[float]:
        """返回长度 n 的 Zipf 累积分布（归一化），cum[i] = Σ_{k<=i} 1/k^α。"""
        weights = [1.0 / ((i + 1) ** alpha) for i in range(n)]
        total = sum(weights)
        cum: List[float] = []
        s = 0.0
        for w in weights:
            s += w
            cum.append(s / total)
        # 浮点兜底：末位置 1.0
        cum[-1] = 1.0
        return cum

    @staticmethod
    def _sample_cdf(rng: random.Random, cum: List[float]) -> int:
        """按累积分布 cum 采样一个下标（二分查找）。"""
        r = rng.random()
        lo, hi = 0, len(cum) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if cum[mid] < r:
                lo = mid + 1
            else:
                hi = mid
        return lo

    @staticmethod
    def _bounded_pareto(rng: random.Random, x_m: int, x_M: int,
                        alpha: float) -> int:
        """从 [x_m, x_M] 上的 Bounded-Pareto 分布采样一个整数大小。

        CDF: F(x) = (1 - (x_m/x)^α) / (1 - (x_m/x_M)^α)，逆变换采样。
        α <= 0 时退化为 [x_m, x_M] 上的均匀整数。
        """
        if alpha <= 0:
            return rng.randint(x_m, x_M)
        u = rng.random()
        ratio = (x_m / x_M) ** alpha  # (x_m/x_M)^α
        denom = 1.0 - u * (1.0 - ratio)
        if denom <= 0:
            return x_M
        x = x_m / (denom ** (1.0 / alpha))
        val = int(round(x))
        if val < x_m:
            val = x_m
        if val > x_M:
            val = x_M
        return val
