"""algorithms 子包：缓存驱逐策略实现与注册。

所有策略继承 :class:`EvictionPolicy`，通过 ``@register`` 装饰器注册。
- 标准策略（对象级缓存通用）：lru / lfu / fifo / random / randomized_marking / belady。
- 广义缓存策略（面向对象级缓存）：greedy_dual / fractional /
  bit_rounding / fault_rounding / general_rounding。
- 论文《Learning-Augmented Bit-Model Caching》Algorithm 1/2/3 的忠实实现：
  bit_model_online（维护缓存状态分布 µ，自带顶层循环，不兼容 select_victim 接口）。
"""

# 导入所有算法模块以触发 @register 装饰器注册
from cache_sim.algorithms import (  # noqa: F401
    lru,
    lfu,
    fifo,
    random_evict,
    randomized_marking,
    belady,
    greedy_dual,
    fractional,
    bit_rounding,
    fault_rounding,
    general_rounding,
    bit_model_online,
)
