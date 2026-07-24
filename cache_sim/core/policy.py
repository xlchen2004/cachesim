"""驱逐策略抽象接口。

对象级缓存（Content Cache）共用统一的驱逐策略抽象。
策略以可哈希 ``key`` 标识被缓存项：对象级缓存 key = obj_id，在全局缓存内选驱逐对象。

策略维护自身元数据（recency / freq / 分数 x / next_use 等）。
缓存在命中时回调 ``on_hit``、接纳新项后回调 ``on_admit``、驱逐后回调 ``on_evict``，
需要驱逐时调用 ``select_victim``。区分 on_hit / on_admit 是因为 FIFO 只在接纳时
记录插入序、LFU 只在命中时递增频次等。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Hashable, List, Tuple

# "永不再次请求"的哨兵，用于 Belady 的 next_use。
INF = float("inf")


@dataclass
class AccessContext:
    """单次访问的上下文，策略按需读取。

    Attributes:
        time: 逻辑时间 / 请求序号（LRU/FIFO 的 recency、insertion 基准）。
        next_use: 该 key 下一次被请求的时间（Belady 用）；INF 表示不再请求。
        size: 对象大小（对象字节数）。
        cost: 获取成本（广义缓存算法用；bit 模型 cost=size，fault 模型 cost=1）。
        needed: 本次接纳需腾出的空间（缺失对象大小），
            供 Fractional 等算法的 primal-dual 更新使用。
        extra: 预留的分类特征（uint16 元组，如对象类型），当前策略不使用。
    """
    time: int = 0
    next_use: float = INF
    size: float = 1.0
    cost: float = 1.0
    needed: float = 0.0
    extra: Tuple[int, ...] = ()


class EvictionPolicy(ABC):
    """驱逐策略抽象基类。

    子类需实现 on_hit / on_admit / on_evict / select_victim / reset。
    离线算法（如 Belady）将类属性 ``offline`` 置为 True。
    """

    name: str = "policy"
    offline: bool = False

    def __init__(self, name: str = ""):
        self.name = name or self.__class__.__name__

    @abstractmethod
    def on_hit(self, key: Hashable, ctx: "AccessContext") -> None:
        """命中时更新元数据。"""
        ...

    @abstractmethod
    def on_admit(self, key: Hashable, ctx: "AccessContext") -> None:
        """接纳新项后更新元数据。"""
        ...

    @abstractmethod
    def on_evict(self, key: Hashable) -> None:
        """驱逐后清理元数据。"""
        ...

    @abstractmethod
    def select_victim(self, candidates: List[Hashable],
                      ctx: "AccessContext") -> Hashable:
        """从候选 key 中选一个驱逐对象。

        Args:
            candidates: 当前可被驱逐的 key 列表（缓存内全部对象 id）。
            ctx: 触发本次驱逐的访问上下文。

        Returns:
            被选中的 key。调用方（缓存）负责真正移除该项并回调 on_evict。
        """
        ...

    def reset(self) -> None:
        """重置内部状态。子类应覆盖以清空自身元数据。"""
        pass
