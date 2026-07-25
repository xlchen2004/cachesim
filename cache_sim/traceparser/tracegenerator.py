"""合成 trace 生成器（对象级缓存）。

提供 :meth:`SyntheticGenerator.gen_content`：均匀 / Zipf 流行度、固定大小的
``(time, id, size, extra)`` 对象级 trace，用于算法评估与测试。

Pareto / Bounded-Pareto 的 ``basic_trace`` 生成器（``basic_trace.cc`` 的忠实 Python
复现）见 :mod:`cache_sim.traceparser.basic_trace`。
"""

import random
from typing import List, Optional, Tuple

from cache_sim.traceparser.reader import Access

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
