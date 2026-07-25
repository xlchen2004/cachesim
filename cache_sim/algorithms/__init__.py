"""algorithms 子包：缓存驱逐策略实现与注册。

所有策略继承 :class:`EvictionPolicy`，通过 ``@register`` 装饰器注册。
- 标准策略（对象级缓存通用）：lru / lfu / fifo / random / randomized_marking / belady。
- 论文《Learning-Augmented Bit-Model Caching》Algorithm 1/2/3 的忠实实现：
  bit_model_online（维护缓存状态分布 µ，自带顶层循环，不兼容 select_victim 接口）。
"""

# 导入所有算法模块以触发 @register 装饰器注册
# 使用 import 全路径避免包初始化期间的命名查找问题
import cache_sim.algorithms.lru  # noqa: F401
import cache_sim.algorithms.lfu  # noqa: F401
import cache_sim.algorithms.fifo  # noqa: F401
import cache_sim.algorithms.random_evict  # noqa: F401
import cache_sim.algorithms.randomized_marking  # noqa: F401
import cache_sim.algorithms.belady  # noqa: F401
import cache_sim.algorithms.bit_model_online  # noqa: F401
