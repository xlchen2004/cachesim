"""算法注册机制。

提供 register 装饰器用于注册缓存算法，get_algorithm 工厂函数用于按名称实例化算法。
当前为骨架实现，后续将随具体算法实现一起完善。
"""

_ALGORITHM_REGISTRY = {}


def register(name):
    """算法注册装饰器。

    用法:
        @register("lru")
        class LRUAlgorithm(CacheAlgorithm):
            ...

    Args:
        name: 算法注册名称

    Returns:
        类装饰器
    """
    def decorator(cls):
        _ALGORITHM_REGISTRY[name] = cls
        return cls
    return decorator


def get_algorithm(name, **params):
    """按名称获取并实例化已注册的算法。

    Args:
        name: 算法注册名称
        **params: 传递给算法构造函数的参数

    Returns:
        算法实例

    Raises:
        KeyError: 当 name 未注册时
    """
    if name not in _ALGORITHM_REGISTRY:
        raise KeyError(f"未注册的算法: {name}，已注册: {list(_ALGORITHM_REGISTRY.keys())}")
    return _ALGORITHM_REGISTRY[name](**params)


def list_algorithms():
    """返回所有已注册算法的名称列表"""
    return list(_ALGORITHM_REGISTRY.keys())
