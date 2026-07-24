"""对象级缓存（Content Cache）数据模型。

按 ``项目设计.md`` 仅实现对象级缓存：面向 (time, id, size[, extra]) trace，
按字节容量管理变长对象，统计 OHR（对象命中率）与 BHR（字节命中率）。

trace 记录格式（空格分隔，3 列必需 + 预留 extra 列）：
  - time: long long int，当前未使用（留待未来 TTL 特性）。
  - id: long long int，对象唯一标识。
  - size: uint32，对象大小（字节）。
  - extra: 可选 uint16 分类特征（如对象类型），预留，当前策略不使用。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from cache_sim.core.policy import INF, AccessContext, EvictionPolicy


@dataclass
class _ObjectEntry:
    size: int
    next_seq: float = INF


class ContentCache:
    """对象级缓存（Content Cache）。

    按字节容量管理变长对象。维护 capacity / remain（admit 减 size，evict 加回 size），
    统计 OHR（对象命中率）= obj_hit/obj_total 与 BHR（字节命中率）= byte_hit/byte_total。

    Attributes:
        capacity: 总容量（字节）。
        remain: 剩余空间（字节）。
        eviction_policy: 驱逐策略。
        offline: 是否离线。
        cost_model: 成本模型，"bit"(cost=size) / "fault"(cost=1) / "general"(cost=size)。
    """

    def __init__(self, capacity: int, eviction_policy: EvictionPolicy,
                 cost_model: str = "bit", offline: Optional[bool] = None):
        if capacity <= 0:
            raise ValueError(f"capacity 必须为正，得到 {capacity}")
        self.capacity = int(capacity)
        self.remain = int(capacity)
        self.eviction_policy = eviction_policy
        self.cost_model = cost_model
        self.offline = bool(offline) if offline is not None else getattr(eviction_policy, "offline", False)

        self._objects: Dict[int, _ObjectEntry] = {}
        self.obj_total = 0
        self.obj_hit = 0
        self.byte_total = 0
        self.byte_hit = 0
        self.evictions = 0
        self._competitive_ratio: Optional[float] = None

    def _cost(self, size: int) -> float:
        if self.cost_model == "fault":
            return 1.0
        # bit 与 general 默认均以 size 为成本
        return float(size)

    def access(self, seq: int, obj_id: int, size: int,
               next_seq: float = INF, extra: Tuple[int, ...] = ()) -> bool:
        """模拟一次对象访问，返回是否命中。

        Args:
            seq: 请求序号（时间轴，用于 recency / insertion）。
            obj_id: 对象唯一标识。
            size: 对象大小（字节）。
            next_seq: 该对象下一次被请求的序号（仅 Belady 用）。
            extra: 预留的分类特征（uint16 元组），当前策略不使用。
        """
        self.obj_total += 1
        self.byte_total += size
        ctx = AccessContext(time=seq, next_use=next_seq, size=size,
                            cost=self._cost(size), extra=extra)

        if obj_id in self._objects:
            self.obj_hit += 1
            self.byte_hit += size
            self._objects[obj_id].next_seq = next_seq
            self.eviction_policy.on_hit(obj_id, ctx)
            return True

        self._admit(obj_id, size, next_seq, ctx)
        return False

    def _admit(self, obj_id: int, size: int, next_seq: float,
               ctx: AccessContext) -> None:
        """驱逐至剩余空间足够后接纳新对象。对象大于总容量时不接纳。"""
        ctx.needed = max(0.0, size - self.remain)
        while size > self.remain and self._objects:
            candidates = list(self._objects.keys())
            victim = self.eviction_policy.select_victim(candidates, ctx)
            entry = self._objects.pop(victim)
            self.remain += entry.size
            self.eviction_policy.on_evict(victim)
            self.evictions += 1
        if size <= self.capacity:
            self._objects[obj_id] = _ObjectEntry(size=size, next_seq=next_seq)
            self.remain -= size
            self.eviction_policy.on_admit(obj_id, ctx)
        # 否则对象大于总容量，无法缓存，丢弃

    def reset(self) -> None:
        self.remain = self.capacity
        self._objects.clear()
        self.obj_total = 0
        self.obj_hit = 0
        self.byte_total = 0
        self.byte_hit = 0
        self.evictions = 0
        self._competitive_ratio = None
        self.eviction_policy.reset()

    def set_competitive_ratio(self, ratio: Optional[float]) -> None:
        self._competitive_ratio = ratio

    def get_result(self, dataset: str = "") -> "SimulationResult":
        return SimulationResult(
            cache_type="content",
            algorithm=self.eviction_policy.name,
            dataset=dataset,
            config={
                "capacity": self.capacity,
                "cost_model": self.cost_model,
                "offline": self.offline,
            },
            total_requests=self.obj_total,
            hits=self.obj_hit,
            misses=self.obj_total - self.obj_hit,
            byte_total=self.byte_total,
            byte_hit=self.byte_hit,
            evictions=self.evictions,
            competitive_ratio=self._competitive_ratio,
        )


@dataclass
class SimulationResult:
    """单次模拟结果。

    total_requests=obj_total, hits=obj_hit, byte_total/byte_hit 为字节统计。
    """
    cache_type: str
    algorithm: str
    dataset: str
    config: Dict[str, Any] = field(default_factory=dict)
    total_requests: int = 0
    hits: int = 0
    misses: int = 0
    byte_total: int = 0
    byte_hit: int = 0
    evictions: int = 0
    competitive_ratio: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def hit_rate(self) -> float:
        """对象命中率 OHR = hits/total_requests。"""
        return self.hits / self.total_requests if self.total_requests > 0 else 0.0

    @property
    def ohr(self) -> float:
        """对象命中率。"""
        return self.hit_rate

    @property
    def bhr(self) -> float:
        """字节命中率 = byte_hit/byte_total。"""
        return self.byte_hit / self.byte_total if self.byte_total > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cache_type": self.cache_type,
            "algorithm": self.algorithm,
            "dataset": self.dataset,
            "config": self.config,
            "total_requests": self.total_requests,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": self.hit_rate,
            "byte_total": self.byte_total,
            "byte_hit": self.byte_hit,
            "bhr": self.bhr,
            "evictions": self.evictions,
            "competitive_ratio": self.competitive_ratio,
            "extra": self.extra,
        }

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str)

    def to_csv_row(self) -> Dict[str, Any]:
        d = self.to_dict()
        d.pop("extra", None)
        d.pop("config", None)
        return d
