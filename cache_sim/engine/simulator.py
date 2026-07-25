"""模拟引擎。

驱动对象级缓存（ContentCache）遍历 trace，处理命中 / 未命中 / 驱逐。
离线算法（Belady）需预知未来：模拟器先预计算每个对象的 next-use，再正向模拟。

竞争比 = online_misses / belady_misses，由 :func:`compute_competitive_ratio`
计算后回填到结果中。
"""

from typing import Callable, Iterable, List, Optional, Tuple

from cache_sim.core.models import ContentCache, SimulationResult
from cache_sim.core.policy import INF, EvictionPolicy


def precompute_next_use(keys: List) -> List[float]:
    """反向扫描，next_use[i] = i 之后下一个相同 key 的索引，无则 INF。"""
    n = len(keys)
    next_use = [INF] * n
    next_idx = {}
    for i in range(n - 1, -1, -1):
        k = keys[i]
        next_use[i] = next_idx.get(k, INF)
        next_idx[k] = i
    return next_use


def _extra_of(item) -> Tuple[int, ...]:
    """从 trace 记录中取出 extra 元组（兼容 3/4 元组）。"""
    return item[3] if len(item) >= 4 else ()


class ContentSimulator:
    """对象级缓存模拟器。

    遍历 (time, id, size[, extra]) trace，驱动 :class:`ContentCache`。
    seq 由模拟器按请求序生成（time 列当前未使用，留待未来 TTL）。

    trace 的完整性检查在启动时由调用方（CLI / ExperimentRunner）通过
    :func:`cache_sim.traceparser.check_trace` 完成；读取器本身亦逐行内联校验。
    """

    def __init__(self, policy: EvictionPolicy, capacity: int,
                 cost_model: str = "bit", dataset_name: str = ""):
        self.policy = policy
        self.dataset_name = dataset_name
        self.cache = ContentCache(capacity, policy, cost_model)

    def run(self, trace: Iterable[Tuple]) -> SimulationResult:
        """运行模拟。

        Args:
            trace: (time, id, size[, extra]) 记录的可迭代对象。
        """
        self.cache.reset()
        if self.cache.offline:
            result = self._run_offline(trace)
        else:
            seq = 0
            for item in trace:
                seq += 1
                _time, obj_id, size = item[0], item[1], item[2]
                self.cache.access(seq, obj_id, size, extra=_extra_of(item))
            result = self.cache.get_result(self.dataset_name)
        # 离线最优（Belady）的竞争比为 1.0
        if getattr(self.policy, "offline", False):
            result.competitive_ratio = 1.0
        return result

    def _run_offline(self, trace: Iterable[Tuple]) -> SimulationResult:
        """Belady：预计算每个对象的 next_seq 后正向模拟。"""
        items = list(trace)  # 离线需随机访问，物化整条 trace
        obj_ids = [item[1] for item in items]
        next_use = precompute_next_use(obj_ids)
        for i, item in enumerate(items):
            _t, obj_id, size = item[0], item[1], item[2]
            self.cache.access(i + 1, obj_id, size,
                              next_seq=next_use[i], extra=_extra_of(item))
        return self.cache.get_result(self.dataset_name)


class BitModelOnlineSimulator:
    """Learning-Augmented Bit-Model Caching 专用模拟器（Algorithm 1/2/3）。

    论文算法维护缓存状态分布 µ 而非一次驱逐一个页面，不兼容
    :class:`ContentCache` + ``select_victim`` 接口，故自带顶层循环
    （Algorithm 3）。本模拟器仅负责把 (time, id, size[, extra]) trace 喂给
    :class:`~cache_sim.algorithms.bit_model_online.BitModelOnline` 并返回结果。
    """

    def __init__(self, algo, capacity: int, dataset_name: str = ""):
        self.algo = algo
        self.capacity = capacity
        self.dataset_name = dataset_name

    def run(self, trace: Iterable[Tuple]) -> SimulationResult:
        return self.algo.run(trace, self.capacity, self.dataset_name)


def compute_competitive_ratio(online: SimulationResult,
                              optimal: SimulationResult) -> float:
    """竞争比 = online_misses / optimal_misses。

    optimal 为 Belady 最优。两者均无未命中时为 1.0；optimal 无未命中而 online 有则为 inf。
    """
    if optimal.misses == 0:
        return 1.0 if online.misses == 0 else float("inf")
    return online.misses / optimal.misses


def compute_bit_cost_ratio(online: SimulationResult,
                           belady: SimulationResult) -> float:
    """Bit-model 代价竞争比 = online_fetch_cost / belady_byte_misses。

    Bit 模型代价 = 取回字节数。Belady 的 bit 代价 = 字节未命中量
    （byte_total − byte_hit）；在线算法的 fetch_cost 来自结果 ``extra``（含分布
    更新可能额外取回的页面）。Belady 代价为 0 时：在线也为 0 返回 1.0，否则 inf。
    """
    belady_cost = belady.byte_total - belady.byte_hit
    online_cost = online.extra.get("fetch_cost", 0.0)
    if belady_cost <= 0:
        return 1.0 if online_cost <= 0 else float("inf")
    return online_cost / belady_cost


def run_with_competitive_ratio(
    sim_factory: Callable[[EvictionPolicy], "object"],
    trace,
    online_policy: EvictionPolicy,
    belady_policy: Optional[EvictionPolicy] = None,
) -> Tuple[SimulationResult, Optional[SimulationResult]]:
    """运行在线策略，并可选地运行 Belady 基线以回填竞争比。

    Args:
        sim_factory: 给定策略返回一个模拟器（含 run 方法）。
        trace: trace 可迭代对象。注意：离线运行会物化 trace，在线流式消费。
            若同时跑在线与 Belady，调用方应传入可重复遍历的 trace（如 list 或可重开的读取器）。
        online_policy: 在线策略实例。
        belady_policy: 可选 Belady 策略实例；为 None 时不计算竞争比。

    Returns:
        (online_result, belady_result_or_None)。online_result.competitive_ratio 已回填。
    """
    online_result = sim_factory(online_policy).run(trace)
    if belady_policy is None:
        return online_result, None
    belady_result = sim_factory(belady_policy).run(trace)
    online_result.competitive_ratio = compute_competitive_ratio(online_result, belady_result)
    belady_result.competitive_ratio = 1.0
    return online_result, belady_result
